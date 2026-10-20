#!/usr/bin/env python3
"""Synthetic ROS graph for network/checkpoint dry-run only.

It never opens serial devices and never publishes a real command.  The dummy
subscriber on /leader/joint_trajectory exists only so the normal preflight can
validate the expected controller-side graph contract.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, JointState
from trajectory_msgs.msg import JointTrajectory

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")


class MockGraph(Node):
    def __init__(self, fps: int):
        super().__init__("omx_remote_inference_mock_graph")
        self.joint_pub = self.create_publisher(JointState, "/joint_states", 10)
        self.camera1_pub = self.create_publisher(CompressedImage, "/camera1/image_raw/compressed", 10)
        self.camera2_pub = self.create_publisher(CompressedImage, "/camera2/image_raw/compressed", 10)
        self.create_subscription(JointTrajectory, "/leader/joint_trajectory", self.on_real_command, 10)
        self.create_subscription(
            JointTrajectory, "/remote_inference/dry_run_joint_trajectory", self.on_dry_command, 10
        )
        self.real_commands = 0
        self.dry_commands = 0
        self.dry_command_times = []
        self.last_dry_positions = []
        self._camera1 = self._encode_image((30, 80, 180), "MOCK WRIST / CAMERA1")
        self._camera2 = self._encode_image((180, 80, 30), "MOCK EXTERNAL / CAMERA2")
        self.timer = self.create_timer(1.0 / fps, self.publish_inputs)

    @staticmethod
    def _encode_image(color, label):
        image = np.full((480, 640, 3), color, dtype=np.uint8)
        cv2.putText(image, label, (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError("Failed to encode mock image")
        return encoded.tobytes()

    def publish_inputs(self):
        stamp = self.get_clock().now().to_msg()
        joints = JointState()
        joints.header.stamp = stamp
        joints.name = list(JOINTS)
        joints.position = [-0.05, -1.88, 1.70, 1.34, 1.57, 0.69]
        self.joint_pub.publish(joints)
        for publisher, data, frame in (
            (self.camera1_pub, self._camera1, "mock_camera1"),
            (self.camera2_pub, self._camera2, "mock_camera2"),
        ):
            msg = CompressedImage()
            msg.header.stamp = stamp
            msg.header.frame_id = frame
            msg.format = "jpeg"
            msg.data = data
            publisher.publish(msg)

    def on_real_command(self, _msg):
        self.real_commands += 1
        self.get_logger().error("Unexpected publication on the REAL command topic")

    def on_dry_command(self, msg):
        self.dry_commands += 1
        self.dry_command_times.append(time.monotonic())
        if msg.points:
            self.last_dry_positions = list(msg.points[0].positions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=90.0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.duration <= 0 or args.fps <= 0:
        raise SystemExit("duration and fps must be positive")
    rclpy.init()
    node = MockGraph(args.fps)
    deadline = time.monotonic() + args.duration
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            try:
                rclpy.spin_once(node, timeout_sec=0.05)
            except ExternalShutdownException:
                break
    finally:
        intervals = np.diff(node.dry_command_times)
        report = {
            "real_command_messages": node.real_commands,
            "dry_run_command_messages": node.dry_commands,
            "last_dry_positions": node.last_dry_positions,
            "dry_run_rate_hz": (
                0.0
                if len(node.dry_command_times) < 2
                else (len(node.dry_command_times) - 1)
                / (node.dry_command_times[-1] - node.dry_command_times[0])
            ),
            "dry_run_interval_ms_p50": 0.0 if not len(intervals) else float(np.percentile(intervals, 50) * 1000),
            "dry_run_interval_ms_p95": 0.0 if not len(intervals) else float(np.percentile(intervals, 95) * 1000),
            "dry_run_interval_ms_p99": 0.0 if not len(intervals) else float(np.percentile(intervals, 99) * 1000),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
