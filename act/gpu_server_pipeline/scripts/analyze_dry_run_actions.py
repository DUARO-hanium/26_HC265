#!/usr/bin/env python3
"""Measure dry-run ACT targets against the latest follower joint state.

This node is read-only: it subscribes to the follower state and the isolated
dry-run trajectory topic and never creates a publisher.
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory


JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")


class DryRunAnalyzer(Node):
    def __init__(self) -> None:
        super().__init__("omx_dry_run_action_analyzer")
        self.latest_state: dict[str, float] | None = None
        self.action_times: list[float] = []
        self.actions: list[list[float]] = []
        self.states_at_action: list[list[float]] = []
        self.abs_deltas: list[list[float]] = []
        self.invalid_messages = 0
        self.create_subscription(JointState, "/joint_states", self.on_state, qos_profile_sensor_data)
        self.create_subscription(
            JointTrajectory,
            "/remote_inference/dry_run_joint_trajectory",
            self.on_action,
            10,
        )

    def on_state(self, msg: JointState) -> None:
        index = {name: i for i, name in enumerate(msg.name)}
        if not all(name in index and index[name] < len(msg.position) for name in JOINTS):
            self.invalid_messages += 1
            return
        values = {name: float(msg.position[index[name]]) for name in JOINTS}
        if not all(math.isfinite(value) for value in values.values()):
            self.invalid_messages += 1
            return
        self.latest_state = values

    def on_action(self, msg: JointTrajectory) -> None:
        if self.latest_state is None or not msg.points:
            self.invalid_messages += 1
            return
        index = {name: i for i, name in enumerate(msg.joint_names)}
        positions = msg.points[0].positions
        if not all(name in index and index[name] < len(positions) for name in JOINTS):
            self.invalid_messages += 1
            return
        action = [float(positions[index[name]]) for name in JOINTS]
        if not all(math.isfinite(value) for value in action):
            self.invalid_messages += 1
            return
        state = [self.latest_state[name] for name in JOINTS]
        self.action_times.append(time.monotonic())
        self.actions.append(action)
        self.states_at_action.append(state)
        self.abs_deltas.append([abs(target - present) for target, present in zip(action, state)])


def summarize(node: DryRunAnalyzer, duration: float) -> dict:
    result: dict = {
        "duration_s": duration,
        "action_messages": len(node.actions),
        "invalid_messages": node.invalid_messages,
        "joint_order": list(JOINTS),
    }
    if len(node.action_times) >= 2:
        intervals = np.diff(np.asarray(node.action_times, dtype=np.float64))
        result["observed_action_rate_hz"] = 1.0 / float(intervals.mean())
        result["action_gap_ms_p95"] = float(np.percentile(intervals, 95) * 1000)
        result["action_gap_ms_max"] = float(intervals.max() * 1000)
    else:
        result["observed_action_rate_hz"] = 0.0
    if node.actions:
        actions = np.asarray(node.actions, dtype=np.float64)
        deltas = np.asarray(node.abs_deltas, dtype=np.float64)
        result["per_joint"] = {
            name: {
                "action_min": float(actions[:, i].min()),
                "action_max": float(actions[:, i].max()),
                "abs_delta_p50": float(np.percentile(deltas[:, i], 50)),
                "abs_delta_p95": float(np.percentile(deltas[:, i], 95)),
                "abs_delta_p99": float(np.percentile(deltas[:, i], 99)),
                "abs_delta_max": float(deltas[:, i].max()),
            }
            for i, name in enumerate(JOINTS)
        }
        result["first_action"] = dict(zip(JOINTS, node.actions[0], strict=True))
        result["first_state_at_action"] = dict(
            zip(JOINTS, node.states_at_action[0], strict=True)
        )
        result["first_abs_delta"] = dict(zip(JOINTS, node.abs_deltas[0], strict=True))
        result["first_max_abs_delta"] = float(max(node.abs_deltas[0]))
        result["last_action"] = dict(zip(JOINTS, node.actions[-1], strict=True))
        result["last_state_at_action"] = dict(
            zip(JOINTS, node.states_at_action[-1], strict=True)
        )
        result["last_abs_delta"] = dict(zip(JOINTS, node.abs_deltas[-1], strict=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("preflight_artifacts/dry_run_actions.json"),
    )
    args = parser.parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")

    rclpy.init()
    node = DryRunAnalyzer()
    deadline = time.monotonic() + args.duration
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        result = summarize(node, args.duration)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        node.destroy_node()
        rclpy.shutdown()

    if result["action_messages"] < 2 or result["invalid_messages"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
