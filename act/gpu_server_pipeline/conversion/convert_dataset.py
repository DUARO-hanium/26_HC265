#!/usr/bin/env python3
"""Convert OMX MCAP episodes to an official LeRobot v3 dataset.

Only source adaptation (ROS decoding, timestamp repair, joint-name ordering,
and bounded interpolation) is implemented here. Dataset serialization is
delegated exclusively to the public LeRobot 0.6.0 API.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from mcap_ros2.reader import read_ros2_messages


FPS = 30
FRAME_NS = 1_000_000_000 / FPS
SHORT_GAP_NS = int(round(2 * FRAME_NS))
MAX_INTERPOLATION_GAP_NS = 100_000_000
MAX_CAMERA_DISTANCE_NS = 50_000_000
DEFAULT_TASK = "Pick a sock from the container and place it on the table"
JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
STATE_TOPIC = "/joint_states"
ACTION_TOPIC = "/leader/joint_trajectory"
PRE_LIMIT_TOPIC = "/leader/joint_trajectory_pre_limit"
CAMERA_KEYS = ("camera1", "camera2")


@dataclass
class NumericStream:
    timestamps_ns: np.ndarray
    values: np.ndarray
    raw_count: int
    regression_drops: int


@dataclass
class CameraStream:
    timestamps_ns: np.ndarray
    frame_indices: np.ndarray
    raw_count: int
    regression_drops: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strictly_monotonic_pairs(
    timestamps_ns: list[int], values: list[Any]
) -> tuple[np.ndarray, list[Any], int]:
    """Drop a regressing pair without separating a value from its timestamp."""
    kept_t: list[int] = []
    kept_v: list[Any] = []
    dropped = 0
    for timestamp, value in zip(timestamps_ns, values, strict=True):
        if kept_t and timestamp <= kept_t[-1]:
            dropped += 1
            continue
        kept_t.append(timestamp)
        kept_v.append(value)
    return np.asarray(kept_t, dtype=np.int64), kept_v, dropped


def canonical_joint_vector(names: list[str], values: list[float]) -> np.ndarray:
    if len(names) != len(values) or len(set(names)) != len(names):
        raise ValueError("invalid or duplicate joint-name/value mapping")
    mapping = dict(zip(names, values, strict=True))
    missing = [name for name in JOINTS if name not in mapping]
    if missing:
        raise ValueError(f"missing canonical joints: {missing}")
    vector = np.asarray([mapping[name] for name in JOINTS], dtype=np.float32)
    if not np.isfinite(vector).all():
        raise ValueError("non-finite joint position")
    return vector


def message_timestamp_ns(decoded: Any, prefer_header: bool) -> int:
    if prefer_header and hasattr(decoded.ros_msg, "header"):
        stamp = decoded.ros_msg.header.stamp
        timestamp = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
        if timestamp > 0:
            return timestamp
    return int(decoded.log_time_ns)


def load_numeric_streams(mcap_path: Path) -> tuple[NumericStream, NumericStream, dict[str, Any]]:
    state_t: list[int] = []
    state_v: list[np.ndarray] = []
    action_t: list[int] = []
    action_v: list[np.ndarray] = []
    pre_t: list[int] = []
    pre_v: list[np.ndarray] = []

    for decoded in read_ros2_messages(
        str(mcap_path), topics=[STATE_TOPIC, ACTION_TOPIC, PRE_LIMIT_TOPIC]
    ):
        topic = decoded.channel.topic
        msg = decoded.ros_msg
        if topic == STATE_TOPIC:
            state_t.append(message_timestamp_ns(decoded, prefer_header=True))
            state_v.append(canonical_joint_vector(list(msg.name), list(msg.position)))
        elif topic in (ACTION_TOPIC, PRE_LIMIT_TOPIC):
            if not msg.points:
                continue
            vector = canonical_joint_vector(list(msg.joint_names), list(msg.points[0].positions))
            timestamp = message_timestamp_ns(decoded, prefer_header=False)
            if topic == ACTION_TOPIC:
                action_t.append(timestamp)
                action_v.append(vector)
            else:
                pre_t.append(timestamp)
                pre_v.append(vector)

    state_ts, state_values, state_drops = strictly_monotonic_pairs(state_t, state_v)
    action_ts, action_values, action_drops = strictly_monotonic_pairs(action_t, action_v)
    if len(state_ts) < 2 or len(action_ts) < 2:
        raise ValueError(f"insufficient state/action data in {mcap_path}")

    pre_difference_samples = 0
    if pre_t and action_t:
        pre_ts, pre_values, _ = strictly_monotonic_pairs(pre_t, pre_v)
        for timestamp, value in zip(action_ts, action_values, strict=True):
            idx = int(np.argmin(np.abs(pre_ts - timestamp)))
            if abs(int(pre_ts[idx]) - int(timestamp)) <= 5_000_000 and not np.allclose(
                value, pre_values[idx], atol=1e-7
            ):
                pre_difference_samples += 1

    return (
        NumericStream(
            state_ts, np.stack(state_values).astype(np.float32), len(state_t), state_drops
        ),
        NumericStream(
            action_ts, np.stack(action_values).astype(np.float32), len(action_t), action_drops
        ),
        {"pre_limit_samples": len(pre_t), "post_vs_pre_different_samples": pre_difference_samples},
    )


def load_camera_stream(timestamp_path: Path) -> CameraStream:
    table = pd.read_parquet(timestamp_path)
    required = {"frame_index", "header_stamp_ns"}
    if not required.issubset(table.columns):
        raise ValueError(f"missing camera timestamp columns in {timestamp_path}")
    raw_t = [int(value) for value in table["header_stamp_ns"].tolist()]
    raw_i = [int(value) for value in table["frame_index"].tolist()]
    timestamps, indices, drops = strictly_monotonic_pairs(raw_t, raw_i)
    if len(timestamps) < 2:
        raise ValueError(f"insufficient camera timestamps in {timestamp_path}")
    return CameraStream(
        timestamps,
        np.asarray(indices, dtype=np.int64),
        len(table),
        drops,
    )


def interpolate_bounded(stream: NumericStream, timestamp_ns: int) -> tuple[np.ndarray | None, str]:
    """Linearly interpolate only between real bracketing samples within 100 ms."""
    ts = stream.timestamps_ns
    right = bisect.bisect_left(ts, timestamp_ns)
    if right < len(ts) and int(ts[right]) == timestamp_ns:
        return stream.values[right].copy(), "exact"
    if right == 0 or right == len(ts):
        return None, "outside"
    left = right - 1
    gap = int(ts[right]) - int(ts[left])
    if gap > MAX_INTERPOLATION_GAP_NS:
        return None, "long_gap"
    alpha = (timestamp_ns - int(ts[left])) / gap
    value = stream.values[left] + alpha * (stream.values[right] - stream.values[left])
    label = "short_interpolation" if gap <= SHORT_GAP_NS else "warning_interpolation"
    return value.astype(np.float32), label


def nearest_camera_index(stream: CameraStream, timestamp_ns: int) -> tuple[int | None, int]:
    ts = stream.timestamps_ns
    right = bisect.bisect_left(ts, timestamp_ns)
    candidates = []
    if right < len(ts):
        candidates.append(right)
    if right > 0:
        candidates.append(right - 1)
    if not candidates:
        return None, 2**63 - 1
    best = min(candidates, key=lambda idx: abs(int(ts[idx]) - timestamp_ns))
    distance = abs(int(ts[best]) - timestamp_ns)
    if distance > MAX_CAMERA_DISTANCE_NS:
        return None, distance
    return int(stream.frame_indices[best]), distance


def build_sampling_plan(
    state: NumericStream, action: NumericStream, cameras: dict[str, CameraStream]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_ns = max(
        int(state.timestamps_ns[0]),
        int(action.timestamps_ns[0]),
        *(int(camera.timestamps_ns[0]) for camera in cameras.values()),
    )
    end_ns = min(
        int(state.timestamps_ns[-1]),
        int(action.timestamps_ns[-1]),
        *(int(camera.timestamps_ns[-1]) for camera in cameras.values()),
    )
    if end_ns <= start_ns:
        raise ValueError("streams have no common time interval")

    candidate_count = int(math.floor((end_ns - start_ns) / FRAME_NS)) + 1
    counters = {
        "candidate_grid_frames": candidate_count,
        "state": {"exact": 0, "short_interpolation": 0, "warning_interpolation": 0},
        "action": {"exact": 0, "short_interpolation": 0, "warning_interpolation": 0},
        "drops": {"state_outside": 0, "state_long_gap": 0, "action_outside": 0, "action_long_gap": 0,
                  "camera1_tolerance": 0, "camera2_tolerance": 0},
        "max_camera_distance_ns": {"camera1": 0, "camera2": 0},
    }
    plan: list[dict[str, Any]] = []
    for offset in range(candidate_count):
        timestamp_ns = start_ns + int(round(offset * FRAME_NS))
        state_value, state_label = interpolate_bounded(state, timestamp_ns)
        if state_value is None:
            counters["drops"][f"state_{state_label}"] += 1
            continue
        action_value, action_label = interpolate_bounded(action, timestamp_ns)
        if action_value is None:
            counters["drops"][f"action_{action_label}"] += 1
            continue
        camera_indices: dict[str, int] = {}
        valid = True
        for key, camera in cameras.items():
            frame_index, distance = nearest_camera_index(camera, timestamp_ns)
            counters["max_camera_distance_ns"][key] = max(
                counters["max_camera_distance_ns"][key], int(distance)
            )
            if frame_index is None:
                counters["drops"][f"{key}_tolerance"] += 1
                valid = False
                break
            camera_indices[key] = frame_index
        if not valid:
            continue
        counters["state"][state_label] += 1
        counters["action"][action_label] += 1
        plan.append(
            {
                "source_timestamp_ns": timestamp_ns,
                "state": state_value,
                "action": action_value,
                "state_sampling": state_label,
                "action_sampling": action_label,
                "camera_indices": camera_indices,
            }
        )
    counters["final_frames"] = len(plan)
    counters["retention_ratio"] = len(plan) / candidate_count
    if not plan:
        raise ValueError("sampling plan is empty")
    return plan, counters


class SequentialVideoReader:
    """Read nondecreasing source indices without loading a whole episode in RAM."""

    def __init__(self, path: Path):
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise ValueError(f"cannot open video {path}")
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_index = -1
        self.current_rgb: np.ndarray | None = None

    def get(self, wanted_index: int) -> np.ndarray:
        if wanted_index < self.current_index:
            raise ValueError("camera selection must be nondecreasing")
        while self.current_index < wanted_index:
            ok, bgr = self.capture.read()
            if not ok:
                raise ValueError(
                    f"video ended at frame {self.current_index}, requested {wanted_index}: {self.path}"
                )
            self.current_index += 1
            self.current_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        assert self.current_rgb is not None
        return self.current_rgb.copy()

    def close(self) -> None:
        self.capture.release()


def episode_paths(
    source_root: Path, episode_number: int, episode_dir_template: str
) -> dict[str, Path]:
    """Resolve one Cyclo recording without embedding a user or machine path.

    ``episode_dir_template`` is relative to ``source_root`` and may contain any
    Python format expression for ``episode``, for example
    ``Task_0805_in_package_socks_{episode:02d}_MCAP/0``.
    """
    relative = Path(episode_dir_template.format(episode=episode_number))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("--episode-dir-template must stay below --source-root")
    root = source_root / relative
    video_root = root / "videos" / "0_0"
    return {
        "root": root,
        "mcap": root / "0_0.mcap",
        **{f"{key}_video": video_root / f"{key}.mp4" for key in CAMERA_KEYS},
        **{f"{key}_timestamps": video_root / f"{key}_timestamps.parquet" for key in CAMERA_KEYS},
    }


def validate_inputs(paths: dict[str, Path]) -> None:
    missing = [str(path) for key, path in paths.items() if key != "root" and not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing episode inputs: {missing}")


def convert(args: argparse.Namespace) -> None:
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    audit_root = args.audit_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_root}")
    audit_root.mkdir(parents=True, exist_ok=True)

    features = {
        "observation.images.camera1": {
            "dtype": "video", "shape": (480, 640, 3), "names": ["height", "width", "channel"]
        },
        "observation.images.camera2": {
            "dtype": "video", "shape": (480, 640, 3), "names": ["height", "width", "channel"]
        },
        "observation.state": {"dtype": "float32", "shape": (6,), "names": JOINTS},
        "action": {"dtype": "float32", "shape": (6,), "names": JOINTS},
    }
    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=FPS,
        features=features,
        root=output_root,
        robot_type=args.robot_type,
        use_videos=True,
        image_writer_processes=0,
        image_writer_threads=args.image_writer_threads,
        batch_encoding_size=1,
        rgb_encoder=RGBEncoderConfig(vcodec="h264", pix_fmt="yuv420p", crf=18, g=2),
        encoder_threads=args.encoder_threads,
    )

    audit: dict[str, Any] = {
        "contract": {
            "lerobot_version": "0.6.0", "fps": FPS, "task": args.task, "joints": JOINTS,
            "state_topic": STATE_TOPIC, "action_topic": ACTION_TOPIC,
            "pre_limit_topic_audit_only": PRE_LIMIT_TOPIC,
            "max_interpolation_gap_ns": MAX_INTERPOLATION_GAP_NS,
            "max_camera_distance_ns": MAX_CAMERA_DISTANCE_NS,
            "video": {"codec": "h264", "width": 640, "height": 480, "crf": 18},
        },
        "episodes": [],
    }
    try:
        for output_episode_index, source_episode_number in enumerate(args.episodes):
            paths = episode_paths(
                source_root, source_episode_number, args.episode_dir_template
            )
            validate_inputs(paths)
            state, action, action_audit = load_numeric_streams(paths["mcap"])
            cameras = {
                key: load_camera_stream(paths[f"{key}_timestamps"]) for key in CAMERA_KEYS
            }
            plan, sampling_audit = build_sampling_plan(state, action, cameras)
            mapping_root = audit_root / "frame_mappings"
            mapping_root.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "output_episode_index": output_episode_index,
                    "output_frame_index": np.arange(len(plan), dtype=np.int64),
                    "output_timestamp_s": np.arange(len(plan), dtype=np.float64) / FPS,
                    "source_timestamp_ns": [row["source_timestamp_ns"] for row in plan],
                    "state_sampling": [row["state_sampling"] for row in plan],
                    "action_sampling": [row["action_sampling"] for row in plan],
                    "camera1_source_frame_index": [
                        row["camera_indices"]["camera1"] for row in plan
                    ],
                    "camera2_source_frame_index": [
                        row["camera_indices"]["camera2"] for row in plan
                    ],
                }
            ).to_parquet(
                mapping_root / f"episode_{output_episode_index:06d}_source_{source_episode_number:02d}.parquet",
                index=False,
            )
            readers = {key: SequentialVideoReader(paths[f"{key}_video"]) for key in CAMERA_KEYS}
            try:
                for key, reader in readers.items():
                    if (reader.width, reader.height) != (640, 480):
                        raise ValueError(
                            f"{key} resolution is {reader.width}x{reader.height}, expected 640x480"
                        )
                    if reader.frame_count < cameras[key].raw_count:
                        raise ValueError(
                            f"{key} video frames {reader.frame_count} < timestamp rows {cameras[key].raw_count}"
                        )
                for row in plan:
                    dataset.add_frame(
                        {
                            "observation.images.camera1": readers["camera1"].get(
                                row["camera_indices"]["camera1"]
                            ),
                            "observation.images.camera2": readers["camera2"].get(
                                row["camera_indices"]["camera2"]
                            ),
                            "observation.state": row["state"],
                            "action": row["action"],
                            "task": args.task,
                        }
                    )
                dataset.save_episode(parallel_encoding=True)
            finally:
                for reader in readers.values():
                    reader.close()

            episode_audit = {
                "source_episode": source_episode_number,
                "output_episode_index": output_episode_index,
                "task_source_was_normalized": source_episode_number
                in args.normalized_task_episodes,
                "mcap_sha256": sha256_file(paths["mcap"]),
                "state": {"raw_samples": state.raw_count, "regression_drops": state.regression_drops,
                          "max_source_gap_ns": int(np.diff(state.timestamps_ns).max())},
                "action": {"raw_samples": action.raw_count, "regression_drops": action.regression_drops,
                           "max_source_gap_ns": int(np.diff(action.timestamps_ns).max()), **action_audit},
                "cameras": {
                    key: {
                        "raw_timestamp_rows": cameras[key].raw_count,
                        "regression_pair_drops": cameras[key].regression_drops,
                        "video_frames": readers[key].frame_count,
                        "width": readers[key].width, "height": readers[key].height,
                        "video_sha256": sha256_file(paths[f"{key}_video"]),
                    } for key in CAMERA_KEYS
                },
                "sampling": sampling_audit,
            }
            audit["episodes"].append(episode_audit)
            audit_path = audit_root / "conversion_audit.partial.json"
            audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
            print(
                f"episode {source_episode_number:02d} -> {output_episode_index}: "
                f"{len(plan)} frames, retention={sampling_audit['retention_ratio']:.6f}",
                flush=True,
            )
        dataset.finalize()
    except Exception:
        if dataset.has_pending_frames():
            dataset.clear_episode_buffer(delete_images=True)
        raise

    audit["summary"] = {
        "episode_count": len(audit["episodes"]),
        "total_frames": sum(item["sampling"]["final_frames"] for item in audit["episodes"]),
        "all_tasks": [args.task],
        "finalize_called": True,
    }
    (audit_root / "conversion_audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )


def parse_episodes(spec: str) -> list[int]:
    episodes: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(value) for value in part.split("-", maxsplit=1))
            episodes.extend(range(start, end + 1))
        elif part:
            episodes.append(int(part))
    if not episodes or len(set(episodes)) != len(episodes):
        raise argparse.ArgumentTypeError("episodes must be nonempty and unique")
    return episodes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--repo-id", default="local/0805_in_package_socks")
    parser.add_argument("--episodes", type=parse_episodes, default=parse_episodes("0-40"))
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument(
        "--episode-dir-template",
        default="Task_0805_in_package_socks_{episode:02d}_MCAP/0",
        help="Relative recording path below source root; supports {episode:02d}",
    )
    parser.add_argument(
        "--normalized-task-episodes",
        type=parse_episodes,
        default=parse_episodes("0-3"),
        help="Audit-only list whose task metadata was repaired during conversion",
    )
    parser.add_argument(
        "--robot-type", default="open_manipulator_x_follower_leader"
    )
    parser.add_argument("--image-writer-threads", type=int, default=4)
    parser.add_argument("--encoder-threads", type=int, default=4)
    convert(parser.parse_args())


if __name__ == "__main__":
    main()
