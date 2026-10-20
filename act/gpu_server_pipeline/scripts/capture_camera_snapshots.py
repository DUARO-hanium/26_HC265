#!/usr/bin/env python3
"""Capture one compressed frame from each OMX inference camera for role checks."""

import argparse
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class SnapshotNode(Node):
    def __init__(self, output_dir: Path):
        super().__init__("omx_camera_snapshot")
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.received: set[str] = set()
        self.create_subscription(
            CompressedImage,
            "/camera1/image_raw/compressed",
            lambda msg: self.save("camera1", msg),
            qos_profile_sensor_data,
        )
        self.create_subscription(
            CompressedImage,
            "/camera2/image_raw/compressed",
            lambda msg: self.save("camera2", msg),
            qos_profile_sensor_data,
        )

    def save(self, camera: str, msg: CompressedImage) -> None:
        if camera in self.received:
            return
        suffix = ".png" if "png" in msg.format.lower() else ".jpg"
        path = self.output_dir / f"current_{camera}{suffix}"
        path.write_bytes(bytes(msg.data))
        self.received.add(camera)
        self.get_logger().info(f"saved {camera}: {path} ({len(msg.data)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    rclpy.init()
    node = SnapshotNode(args.output_dir)
    deadline = node.get_clock().now().nanoseconds / 1e9 + args.timeout
    try:
        while len(node.received) < 2:
            now = node.get_clock().now().nanoseconds / 1e9
            if now >= deadline:
                missing = {"camera1", "camera2"} - node.received
                raise TimeoutError(f"missing camera snapshots: {sorted(missing)}")
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
