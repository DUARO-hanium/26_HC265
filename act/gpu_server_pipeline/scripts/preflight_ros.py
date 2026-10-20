#!/usr/bin/env python3
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from dynamixel_interfaces.msg import DynamixelState
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, JointState

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")


class Preflight(Node):
    def __init__(self):
        super().__init__("omx_remote_inference_preflight")
        self.times = {"joint_states": [], "dxl_state": [], "camera1": [], "camera2": []}
        self.source_times = {"joint_states": [], "dxl_state": [], "camera1": [], "camera2": []}
        self.latest_images = {}
        self.joints_ok = False
        self.dxl_comm_states = []
        self.dxl_hardware_errors = []
        self.create_subscription(JointState, "/joint_states", self.on_joint, qos_profile_sensor_data)
        self.create_subscription(
            CompressedImage, "/camera1/image_raw/compressed",
            lambda msg: self.on_image("camera1", msg), qos_profile_sensor_data
        )
        self.create_subscription(
            CompressedImage, "/camera2/image_raw/compressed",
            lambda msg: self.on_image("camera2", msg), qos_profile_sensor_data
        )
        self.create_subscription(
            DynamixelState,
            "/dynamixel_hardware_interface/dxl_state",
            self.on_dxl_state,
            10,
        )

    def on_joint(self, msg):
        self.times["joint_states"].append(time.monotonic())
        self.record_source_time("joint_states", msg)
        self.joints_ok = set(JOINTS).issubset(msg.name) and len(msg.position) >= len(msg.name)

    def on_image(self, key, msg):
        bgr = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return
        self.times[key].append(time.monotonic())
        self.record_source_time(key, msg)
        self.latest_images[key] = bgr

    def on_dxl_state(self, msg):
        self.times["dxl_state"].append(time.monotonic())
        self.record_source_time("dxl_state", msg)
        self.dxl_comm_states.append(int(msg.comm_state))
        self.dxl_hardware_errors.extend(int(value) for value in msg.dxl_hw_state if value)

    def record_source_time(self, key, msg):
        stamp = msg.header.stamp
        seconds = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        if seconds > 0:
            self.source_times[key].append(seconds)


def rate(times):
    return 0.0 if len(times) < 2 else (len(times) - 1) / (times[-1] - times[0])


def timing_stats(times, nominal_rate=30.0):
    if len(times) < 2:
        return {"samples": len(times), "gap_ms_p95": None, "gap_ms_max": None,
                "estimated_slots": len(times), "estimated_loss_fraction": 1.0}
    gaps = np.diff(np.asarray(times, dtype=np.float64))
    missed = sum(max(0, round(float(gap) * nominal_rate) - 1) for gap in gaps)
    slots = len(times) + missed
    return {
        "samples": len(times),
        "gap_ms_p95": float(np.percentile(gaps, 95) * 1000),
        "gap_ms_max": float(gaps.max() * 1000),
        "estimated_slots": slots,
        "estimated_loss_fraction": missed / slots if slots else 1.0,
    }


def largest_gap(times):
    if len(times) < 2:
        return None
    values = np.asarray(times, dtype=np.float64)
    gaps = np.diff(values)
    index = int(np.argmax(gaps))
    return {"start": float(values[index]), "end": float(values[index + 1]),
            "gap_s": float(gaps[index])}


def overlapping_common_pause(times_by_topic):
    """Classify a receive-callback pause shared by every input stream."""
    dxl_gap = largest_gap(times_by_topic["dxl_state"])
    if dxl_gap is None:
        return None
    common = ["dxl_state"]
    for key in ("joint_states", "camera1", "camera2"):
        values = times_by_topic[key]
        found = False
        for left, right in zip(values, values[1:]):
            gap = right - left
            overlap = min(right, dxl_gap["end"]) - max(left, dxl_gap["start"])
            if gap >= 0.8 * dxl_gap["gap_s"] and overlap > 0.5 * min(gap, dxl_gap["gap_s"]):
                found = True
                break
        if found:
            common.append(key)
    return {"dxl_receive_gap_ms": dxl_gap["gap_s"] * 1000, "topics": common,
            "all_inputs": len(common) == 4}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--min-rate", type=float, default=25.0)
    parser.add_argument("--warn-dxl-gap", type=float, default=0.12)
    parser.add_argument("--max-dxl-gap", type=float, default=0.50)
    parser.add_argument("--warn-dxl-loss-fraction", type=float, default=0.10)
    parser.add_argument("--max-dxl-loss-fraction", type=float, default=0.20)
    parser.add_argument("--min-dxl-loss-slots", type=int, default=60)
    parser.add_argument("--artifacts", type=Path, default=Path("preflight_artifacts"))
    args = parser.parse_args()
    rclpy.init()
    node = Preflight()
    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)

    errors = []
    rates = {key: rate(values) for key, values in node.times.items()}
    timing = {key: timing_stats(values) for key, values in node.times.items()}
    source_timing = {key: timing_stats(values) for key, values in node.source_times.items()}
    common_pause = overlapping_common_pause(node.times)
    warnings = []
    for key, measured in rates.items():
        if measured < args.min_rate:
            errors.append(f"{key} rate {measured:.2f}Hz < {args.min_rate:.2f}Hz")
    if not node.joints_ok:
        errors.append("canonical six joints missing or malformed in /joint_states")
    dxl_receive_timing = timing["dxl_state"]
    dxl_source_timing = source_timing["dxl_state"]
    source_dxl_available = dxl_source_timing["samples"] >= 2
    dxl_timing = dxl_source_timing if source_dxl_available else dxl_receive_timing
    if not source_dxl_available:
        warnings.append(
            "DYNAMIXEL source timestamps unavailable; rolling source-loss check skipped"
        )
    if dxl_timing["gap_ms_max"] is not None and dxl_timing["gap_ms_max"] > args.max_dxl_gap * 1000:
        errors.append(
            f"dxl_state source max gap {dxl_timing['gap_ms_max']:.1f}ms > "
            f"{args.max_dxl_gap * 1000:.1f}ms"
        )
    elif (
        dxl_timing["gap_ms_max"] is not None
        and dxl_timing["gap_ms_max"] > args.warn_dxl_gap * 1000
    ):
        warnings.append(
            f"dxl_state source max gap warning {dxl_timing['gap_ms_max']:.1f}ms > "
            f"{args.warn_dxl_gap * 1000:.1f}ms; live control will HOLD and resynchronize"
        )
    if (
        dxl_receive_timing["gap_ms_max"] is not None
        and dxl_receive_timing["gap_ms_max"] > args.max_dxl_gap * 1000
        and dxl_timing["gap_ms_max"] is not None
        and dxl_timing["gap_ms_max"] <= args.max_dxl_gap * 1000
        and common_pause is not None
        and common_pause["all_inputs"]
    ):
        warnings.append(
            "common receive-callback pause observed across all inputs; source DXL timestamps remained healthy"
        )
    if (
        source_dxl_available
        and dxl_timing["estimated_slots"] >= args.min_dxl_loss_slots
    ):
        loss = dxl_timing["estimated_loss_fraction"]
        if loss > args.max_dxl_loss_fraction:
            errors.append(
                f"dxl_state source loss {loss:.1%} > "
                f"{args.max_dxl_loss_fraction:.1%}"
            )
        elif loss > args.warn_dxl_loss_fraction:
            warnings.append(
                f"dxl_state source loss warning {loss:.1%} > "
                f"{args.warn_dxl_loss_fraction:.1%}"
            )
    hard_comm = [state for state in node.dxl_comm_states if state not in (0, -7, -11)]
    if hard_comm:
        errors.append(f"non-recoverable DYNAMIXEL comm_state observed: {sorted(set(hard_comm))}")
    if node.dxl_hardware_errors:
        errors.append(
            f"DYNAMIXEL hardware error status observed: {sorted(set(node.dxl_hardware_errors))}"
        )
    for key in ("camera1", "camera2"):
        image = node.latest_images.get(key)
        if image is None or image.shape != (480, 640, 3):
            errors.append(f"{key} missing or not 640x480 color")

    command_topic = "/leader/joint_trajectory"
    pub_count = len(node.get_publishers_info_by_topic(command_topic))
    sub_count = len(node.get_subscriptions_info_by_topic(command_topic))
    if pub_count != 0:
        errors.append(f"{command_topic} already has {pub_count} publisher(s); stop physical leader/teleop")
    if sub_count < 1:
        errors.append(f"{command_topic} has no controller subscriber")

    args.artifacts.mkdir(parents=True, exist_ok=True)
    for key, image in node.latest_images.items():
        cv2.imwrite(str(args.artifacts / f"{key}.jpg"), image)
    report = {
        "rates_hz": rates,
        "timing": timing,
        "source_timing": source_timing,
        "common_receive_pause": common_pause,
        "dxl_nonzero_comm_messages": sum(state != 0 for state in node.dxl_comm_states),
        "dxl_hardware_error_messages": len(node.dxl_hardware_errors),
        "joint_names_ok": node.joints_ok,
        "command_publishers_before_client": pub_count,
        "command_subscribers": sub_count,
        "camera1_expected_role": "wrist",
        "camera2_expected_role": "external",
        "errors": errors,
        "warnings": warnings,
    }
    (args.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    node.destroy_node()
    rclpy.shutdown()
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
