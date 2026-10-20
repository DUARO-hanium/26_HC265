#!/usr/bin/env python3
"""Single-arm ACT and sequential ACT, using official LeRobot + ROBOTIS RobotClient."""
import argparse
import json
from pathlib import Path
import select
import sys
import time

import numpy as np
import torch
import yaml

from lerobot_engine.image_preprocessing import prepare_policy_image
from lerobot_engine.loading import LoadingMixin
from robot_client import RobotClient


IMAGE_KEYS = {'observation.images.top', 'observation.images.wrist'}


def model_directory(path):
    root = Path(LoadingMixin._resolve_model_dir(str(path)))
    for filename in ('config.json', 'model.safetensors'):
        if not (root / filename).is_file():
            raise ValueError(f'Missing checkpoint file: {root / filename}')
    return root


class Arm:
    def __init__(self, side, path, settings, connect=True):
        self.side, self.settings, self.robot = side, settings, None
        root = model_directory(path)
        raw = json.loads((root / 'config.json').read_text())
        if (raw.get('type') != 'act'
                or raw.get('input_features', {}).get('observation.state', {}).get('shape') != [6]
                or raw.get('output_features', {}).get('action', {}).get('shape') != [6]
                or {k for k in raw['input_features'] if k.startswith('observation.images.')} != IMAGE_KEYS):
            raise ValueError(f'{side}: expected ACT, 6 radian state/actions, top + wrist images')
        self.policy, self.pre, self.post = LoadingMixin._load_policy_assets(
            str(root), torch.device(settings['device']))
        self.policy.reset()
        self.last = None
        if connect:
            self.robot = RobotClient(f'omx_ai_{side}', router_port=7449, domain_id=74,
                                     enable_command_publishers=True)
            try:
                if not self.robot.wait_for_ready(timeout=15):
                    raise RuntimeError(f'{side}: joint states or top/wrist images unavailable')
                self.last = self.positions()
            except Exception:
                self.robot.close()
                raise

    def positions(self):
        positions = self.robot.get_joint_positions('follower_arm')
        if positions.shape != (6,) or not np.isfinite(positions).all():
            raise RuntimeError(f'{self.side}: invalid joint state')
        return positions

    def fresh(self):
        timestamps = [self.robot.get_joint_timestamp('follower_arm'),
                      *(self.robot.get_image_timestamp(c) for c in ('top', 'wrist'))]
        if any(t is None or time.time() - t > self.settings['max_sensor_age_s'] for t in timestamps):
            raise RuntimeError(f'{self.side}: stale joint/camera stream; holding last target')

    def batch(self, features):
        images = self.robot.get_images(format='rgb')
        batch = {}
        for key, feature in features.items():
            if not key.startswith('observation.images.'):
                continue
            name = key.removeprefix('observation.images.')
            camera = self.robot._config['cameras'][name]
            _, height, width = feature.shape
            image = prepare_policy_image(images[name], rotation_deg=camera.get('rotation_deg', 0),
                                         target_size=(width, height))
            batch[key] = torch.from_numpy(image.copy()).permute(2, 0, 1).float().unsqueeze(0) / 255
        batch['observation.state'] = torch.from_numpy(self.positions().copy()).float().unsqueeze(0)
        batch['task'] = ['']
        return batch

    @torch.inference_mode()
    def step(self):
        self.fresh()
        batch = self.pre(self.batch(self.policy.config.input_features))
        target = self.post(self.policy.select_action(batch)).detach().cpu().numpy().reshape(-1)
        # Sensors can drop out while CPU inference is running.
        self.fresh()
        if (target.shape != (6,) or not np.isfinite(target).all()
                or np.max(np.abs(target - self.positions())) > self.settings['max_target_error_rad']
                or np.max(np.abs(target - self.last)) > self.settings['max_command_step_rad']):
            raise RuntimeError(f'{self.side}: ACT target exceeds configured radian step bounds; holding')
        self.last = target
        self.hold()

    def hold(self):
        if self.last is not None:
            # Keep the commanded gripper closure at contact.
            self.robot.publish_action(self.last, ['arm'])

    def close(self):
        if self.robot is not None:
            self.robot.close()


class SuccessDetector:
    """Official binary reward classifier; saved normalization is mandatory."""
    def __init__(self, path, settings):
        from lerobot.configs.rewards import RewardModelConfig
        from lerobot.processor import PolicyProcessorPipeline
        from lerobot.rewards.classifier.modeling_classifier import Classifier

        root = model_directory(path)
        cfg = RewardModelConfig.from_pretrained(str(root))
        if cfg.type != 'reward_classifier' or cfg.num_classes != 2 or set(cfg.input_features) != {
                'observation.images.top'}:
            raise ValueError('Success model must be a binary reward_classifier with only observation.images.top')
        cfg.device = settings['device']
        self.model = Classifier.from_pretrained(str(root), config=cfg).to(cfg.device).eval()
        self.pre = PolicyProcessorPipeline.from_pretrained(
            str(root), config_filename='classifier_preprocessor.json',
            overrides={'device_processor': {'device': cfg.device}})
        self.settings = settings['automatic']
        self.since = None
        self.last_image = None

    @torch.inference_mode()
    def ready(self, arm, elapsed):
        arm.fresh()
        stamp = arm.robot.get_image_timestamp('top')
        if stamp == self.last_image:
            self.since = None
            return False
        self.last_image = stamp
        batch = self.pre(arm.batch(self.model.config.input_features))
        probability = float(self.model.predict([batch['observation.images.top']]).probabilities.item())
        velocity = arm.robot.get_joint_velocities('follower_arm')
        stable = (velocity.shape == (6,) and np.isfinite(velocity).all()
                  and np.max(np.abs(velocity)) <= self.settings['max_joint_velocity_rad_s'])
        good = (elapsed >= self.settings['min_left_s'] and stable
                and probability >= self.settings['probability'])
        now = time.monotonic()
        self.since = (self.since or now) if good else None
        dwell = 0 if self.since is None else now - self.since
        print(f'opening_success={probability:.3f} stable={stable} dwell={dwell:.1f}s', flush=True)
        return good and dwell >= self.settings['dwell_s']


def operator_command():
    if select.select([sys.stdin], [], [], 0)[0]:
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError('Operator terminal closed; holding last targets')
        return line.strip().lower() or 'next'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--side', choices=('left', 'right', 'sequence'), default='sequence')
    parser.add_argument('--switch', choices=('manual', 'auto'), default='manual')
    parser.add_argument('--config', default='/omx_ws/config/inference.yaml')
    parser.add_argument('--check', action='store_true', help='Load checkpoint/processors without robot connection')
    args = parser.parse_args()
    settings = yaml.safe_load(Path(args.config).read_text())
    if args.switch == 'auto' and args.side != 'sequence':
        parser.error('--switch auto requires --side sequence')
    if settings['fps'] <= 0 or settings['stage_timeout_s'] <= 0:
        parser.error('fps and stage_timeout_s must be positive')
    torch.set_num_threads(settings['torch_threads'])
    arms = {}
    armed = False
    try:
        detector = SuccessDetector(settings['success_checkpoint'], settings) if args.switch == 'auto' else None
        for side in (('left', 'right') if args.side == 'sequence' else (args.side,)):
            arms[side] = Arm(side, settings[f'{side}_checkpoint'], settings, connect=not args.check)
        if args.check:
            print('Checkpoint(s) and saved processors loaded; no robot connection or commands.')
            return
        print('READY. Type start + Enter to begin. Enter: next stage / finish; p: pause; r: resume; q: hold and quit.', flush=True)
        if input().strip().lower() != 'start':
            return
        armed = True
        stage = next(iter(arms))
        started = time.monotonic()
        next_detector = started
        paused = False
        while True:
            tick = time.monotonic()
            for arm in arms.values():
                arm.fresh()
            command = operator_command()
            if command == 'q':
                break
            if command == 'p':
                paused = True
            elif command == 'r' and paused:
                # Discard queued actions after a pause.
                arms[stage].policy.reset()
                paused = False
                started = tick
            transition = command == 'next'
            if detector and stage == 'left' and not paused and tick >= next_detector:
                transition |= detector.ready(arms['left'], tick - started)
                next_detector = time.monotonic() + 1 / settings['automatic']['check_hz']
            if transition and not paused:
                if stage == 'left' and args.side == 'sequence':
                    arms['left'].hold()
                    stage, started = 'right', time.monotonic()
                    arms['right'].policy.reset()
                    print('RIGHT ACT started. LEFT retains its last commanded grip.', flush=True)
                else:
                    break
            if not paused and tick - started > settings['stage_timeout_s']:
                paused = True
                print('Stage timeout: HOLD. Inspect task; r resumes, Enter after resume advances, q exits.', flush=True)
            if not paused:
                arms[stage].step()
            for side, arm in arms.items():
                if paused or side != stage:
                    arm.hold()
            elapsed = time.monotonic() - tick
            if elapsed > 2 / settings['fps'] and int(tick) != int(tick - elapsed):
                print(f'CPU cycle {elapsed:.3f}s exceeds {1/settings["fps"]:.3f}s target; timing needs measurement.', flush=True)
            time.sleep(max(0, 1 / settings['fps'] - elapsed))
    finally:
        for arm in arms.values():
            try:
                if armed:
                    arm.hold()
            finally:
                arm.close()
        if armed:
            print('ACT stopped. Active position controllers retain their last targets; keep follower bringup running.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'STOP: {exc}', file=sys.stderr)
        sys.exit(1)
