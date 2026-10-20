import logging
import math
import json
import threading
import time
from functools import cached_property

import cv2
import numpy as np
import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import CompressedImage, JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from dynamixel_interfaces.msg import DynamixelState

from lerobot.robots.robot import Robot
from lerobot.types import RobotAction, RobotObservation

from .config_ros2_omx import Ros2OmxConfig
from .dxl_health import DxlHealthMonitor, startup_snapshot_acceptable

logger = logging.getLogger(__name__)

JOINT_NAMES = (
    "joint1",
    "joint2",
    "joint3",
    "joint4",
    "joint5",
    "gripper_joint_1",
)
REAL_HARDWARE_CONFIRMATION = "I_UNDERSTAND_THIS_MOVES_OMX"


class TransientInputFreshnessError(RuntimeError):
    """A bounded, retryable observation freshness/coherence condition."""


class RecoverableDxlArrivalStale(TransientInputFreshnessError):
    """Local DXL delivery is late, but has not crossed the terminal deadline."""


def start_pose_violations(
    current: dict[str, float], target: dict[str, float], tolerance_rad: float
) -> dict[str, dict[str, float]]:
    return {
        name: {"current": current[name], "target": target[name], "delta": current[name] - target[name]}
        for name in JOINT_NAMES
        if abs(current[name] - target[name]) > tolerance_rad
    }


def absolute_limit_violations(
    values: dict[str, float], limits: dict[str, tuple[float, float]], tolerance_rad: float = 0.0
) -> dict[str, dict[str, float]]:
    return {
        name: {"value": values[name], "min": limits[name][0], "max": limits[name][1]}
        for name in JOINT_NAMES
        if not limits[name][0] - tolerance_rad <= values[name] <= limits[name][1] + tolerance_rad
    }


class Ros2Omx(Robot):
    """LeRobot Robot backed by the existing ROS 2 OMX control graph.

    This adapter never opens an OpenRB serial port. ros2_control remains the
    sole hardware owner. Camera ordering and joint ordering match the training
    dataset contract exactly.
    """

    config_class = Ros2OmxConfig
    name = "ros2_omx"

    def __init__(self, config: Ros2OmxConfig):
        super().__init__(config)
        self.config = config
        self._connected = False
        self._owns_rclpy = False
        self._lock = threading.Lock()
        self._command_lock = threading.RLock()
        self._joint_positions: dict[str, float] | None = None
        self._joint_time = 0.0
        self._images: dict[str, np.ndarray] = {}
        self._image_times: dict[str, float] = {}
        self._executor: MultiThreadedExecutor | None = None
        self._spin_thread: threading.Thread | None = None
        self._safe_stop_done = False
        # Command/action limits are terminal safety gates.  The measured
        # observation-state extrema are empirical training-support telemetry,
        # not physical joint limits (matching official LeRobot normalization).
        self._action_limits: dict[str, tuple[float, float]] = {}
        self._state_limits: dict[str, tuple[float, float]] = {}
        self._training_start_pose: dict[str, float] = {}
        self._consecutive_clamps = 0
        self._absolute_saturation_count = 0
        self._gripper_command_count = 0
        self._gripper_hold_latched = False
        self._gripper_release_count = 0
        self._last_commanded_positions: list[float] | None = None
        self._first_observation_pending = True
        self._first_action_pending = True
        self._last_state_support_warning_at = 0.0
        self._dxl_health = DxlHealthMonitor(
            nominal_rate_hz=config.fps,
            window_s=config.dxl_loss_window_s,
            source_gap_timeout_s=config.dxl_source_gap_timeout_s,
            arrival_stale_timeout_s=config.dxl_arrival_stale_timeout_s,
            arrival_fault_timeout_s=config.dxl_arrival_fault_timeout_s,
            max_loss_fraction=config.max_dxl_loss_fraction,
            min_slots=config.min_dxl_loss_slots,
        )
        self._last_dxl_resync_generation = self._dxl_health.resync_generation()

        if not config.dry_run:
            if config.real_hardware_confirmation != REAL_HARDWARE_CONFIRMATION:
                raise RuntimeError("Real hardware requires the explicit confirmation token")
            if config.max_relative_target is None or config.max_relative_target <= 0:
                raise RuntimeError("Real hardware requires a positive max_relative_target")
            if config.max_gripper_relative_target is None or config.max_gripper_relative_target <= 0:
                raise RuntimeError("Real hardware requires a positive max_gripper_relative_target")
            if not config.safety_limits_path:
                raise RuntimeError("Real hardware requires an audited safety_limits_path")
            if not config.state_limits_path:
                raise RuntimeError("Real hardware requires an audited state_limits_path")
            if not config.training_start_pose_path:
                raise RuntimeError("Real hardware requires a training_start_pose_path")
            raw = json.loads(open(config.safety_limits_path, encoding="utf-8").read())
            if set(raw) != set(JOINT_NAMES):
                raise ValueError("Safety limit keys must exactly match the canonical six joints")
            self._action_limits = {
                name: (float(raw[name]["min"]), float(raw[name]["max"])) for name in JOINT_NAMES
            }
            if not all(math.isfinite(lo) and math.isfinite(hi) and lo < hi
                       for lo, hi in self._action_limits.values()):
                raise ValueError("Invalid action safety limits")
            if config.gripper_hold_enabled:
                gripper_min, gripper_max = self._action_limits["gripper_joint_1"]
                if not gripper_min <= config.gripper_hold_target_rad <= gripper_max:
                    raise ValueError(
                        "gripper_hold_target_rad is outside the audited action envelope"
                    )
            state_raw = json.loads(open(config.state_limits_path, encoding="utf-8").read())
            if set(state_raw) != set(JOINT_NAMES):
                raise ValueError("State limit keys must exactly match the canonical six joints")
            self._state_limits = {
                name: (float(state_raw[name]["min"]), float(state_raw[name]["max"]))
                for name in JOINT_NAMES
            }
            if not all(math.isfinite(lo) and math.isfinite(hi) and lo < hi
                       for lo, hi in self._state_limits.values()):
                raise ValueError("Invalid state limits")
            start_raw = json.loads(open(config.training_start_pose_path, encoding="utf-8").read())
            positions = start_raw.get("positions", {})
            if set(positions) != set(JOINT_NAMES):
                raise ValueError("Training start pose keys must exactly match the canonical six joints")
            self._training_start_pose = {name: float(positions[name]) for name in JOINT_NAMES}
            if not all(math.isfinite(value) for value in self._training_start_pose.values()):
                raise ValueError("Training start pose contains non-finite values")

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        motors = {f"{name}.pos": float for name in JOINT_NAMES}
        images = {
            "camera1": (self.config.height, self.config.width, 3),
            "camera2": (self.config.height, self.config.width, 3),
        }
        return {**motors, **images}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {f"{name}.pos": float for name in JOINT_NAMES}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        return None

    def configure(self) -> None:
        return None

    def connect(self, calibrate: bool = True) -> None:
        if self._connected:
            raise RuntimeError("ROS 2 OMX adapter is already connected")
        if not rclpy.ok():
            # Keep SIGINT from invalidating the ROS context before SafeRobotClient
            # can publish its final hold command. The main thread handles
            # KeyboardInterrupt, calls disconnect/safe_stop, then shuts down.
            rclpy.init(args=None, signal_handler_options=SignalHandlerOptions.NO)
            self._owns_rclpy = True

        self._node = rclpy.create_node("lerobot_ros2_omx_client")
        state_group = MutuallyExclusiveCallbackGroup()
        dxl_group = MutuallyExclusiveCallbackGroup()
        camera1_group = MutuallyExclusiveCallbackGroup()
        camera2_group = MutuallyExclusiveCallbackGroup()
        # Limit OpenCV's internal pool in this process. Two camera callbacks
        # already run independently; nested 8-thread decode pools can starve
        # lightweight state callbacks on an 8-core WSL container.
        cv2.setNumThreads(1)
        camera_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._node.create_subscription(
            JointState,
            self.config.joint_state_topic,
            self._on_joint_state,
            qos_profile_sensor_data,
            callback_group=state_group,
        )
        self._node.create_subscription(
            CompressedImage, self.config.camera1_topic,
            lambda msg: self._on_image("camera1", msg), camera_qos,
            callback_group=camera1_group,
        )
        self._node.create_subscription(
            CompressedImage, self.config.camera2_topic,
            lambda msg: self._on_image("camera2", msg), camera_qos,
            callback_group=camera2_group,
        )
        self._node.create_subscription(
            DynamixelState,
            self.config.dxl_state_topic,
            self._on_dxl_state,
            10,
            callback_group=dxl_group,
        )
        output_topic = self.config.dry_run_topic if self.config.dry_run else self.config.command_topic
        self._publisher = self._node.create_publisher(JointTrajectory, output_topic, 10)
        self._executor = MultiThreadedExecutor(num_threads=4)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._spin_thread.start()
        self._connected = True

        deadline = time.monotonic() + self.config.startup_timeout_s
        probation_started_at: float | None = None
        while time.monotonic() < deadline:
            with self._lock:
                ready = self._joint_positions is not None and set(self._images) == {"camera1", "camera2"}
            ready = ready and self._dxl_health.snapshot(time.monotonic()).seen
            if ready:
                now = time.monotonic()
                dxl_snapshot = self._dxl_health.snapshot(now)
                if dxl_snapshot.hard_fault:
                    self.disconnect()
                    raise RuntimeError(dxl_snapshot.hard_fault)
                startup_dxl_healthy = startup_snapshot_acceptable(
                    dxl_snapshot,
                    max_age_s=self.config.dxl_arrival_stale_timeout_s,
                    max_loss_fraction=self.config.max_dxl_loss_fraction,
                )
                if not startup_dxl_healthy:
                    # Re-anchor non-hard setup/descheduling loss before any
                    # action.  Startup uses the same bounded-loss policy as
                    # live control instead of demanding an unrealistic 0.0%.
                    # This never clears latched hardware/communication faults.
                    self._dxl_health.reset_nonhard_history()
                    probation_started_at = None
                    time.sleep(0.02)
                    continue
                if probation_started_at is None:
                    probation_started_at = now
                if now - probation_started_at < self.config.startup_health_probation_s:
                    time.sleep(0.02)
                    continue
                self._dxl_health.reset_nonhard_history()
                if self._training_start_pose:
                    with self._lock:
                        assert self._joint_positions is not None
                        current_positions = dict(self._joint_positions)
                        violations = start_pose_violations(
                            current_positions,
                            self._training_start_pose,
                            self.config.training_start_tolerance_rad,
                        )
                    if violations:
                        self.disconnect()
                        raise RuntimeError(
                            "Follower is outside the audited training start pose; "
                            f"real inference refused: {violations}"
                        )
                    self._warn_state_support_violations(
                        current_positions, context="startup"
                    )
                logger.info(
                    "ROS inputs ready after %.1fs healthy DXL startup probation; "
                    "command output=%s dry_run=%s",
                    self.config.startup_health_probation_s,
                    output_topic,
                    self.config.dry_run,
                )
                return
            time.sleep(0.02)
        self.disconnect()
        raise TimeoutError("Timed out waiting for joint, DYNAMIXEL, and both camera streams")

    def _on_dxl_state(self, msg: DynamixelState) -> None:
        source_time_s = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        self._dxl_health.observe(
            time.monotonic(),
            source_time_s=source_time_s,
            comm_state=int(msg.comm_state),
            ids=tuple(int(value) for value in msg.id),
            dxl_hw_state=tuple(int(value) for value in msg.dxl_hw_state),
        )

    def health_fault_reason(self) -> str | None:
        return self._dxl_health.fault_reason(time.monotonic()) or self._command_conflict_reason()

    def _command_conflict_reason(self) -> str | None:
        """Reject a second command source that bypasses this adapter's guards."""
        if not self._connected:
            return None
        publisher_count = self._node.count_publishers(self.config.command_topic)
        allowed = 0 if self.config.dry_run else 1
        if publisher_count > allowed:
            return (
                f"Competing command publisher(s) on {self.config.command_topic}: "
                f"observed={publisher_count}, allowed={allowed}"
            )
        return None

    def health_warning_reason(self) -> str | None:
        return self._dxl_health.warning_reason(
            time.monotonic(), self.config.warn_dxl_loss_fraction
        )

    def _on_joint_state(self, msg: JointState) -> None:
        index = {name: i for i, name in enumerate(msg.name)}
        if not all(name in index for name in JOINT_NAMES):
            return
        if any(index[name] >= len(msg.position) for name in JOINT_NAMES):
            logger.error("Rejected malformed JointState: position array is too short")
            return
        values = {name: float(msg.position[index[name]]) for name in JOINT_NAMES}
        if not all(math.isfinite(v) for v in values.values()):
            logger.error("Rejected non-finite joint state")
            return
        with self._lock:
            self._joint_positions = values
            self._joint_time = time.monotonic()

    def _on_image(self, key: str, msg: CompressedImage) -> None:
        received_at = time.monotonic()
        encoded = np.frombuffer(msg.data, dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if bgr is None:
            logger.error("Failed to decode %s", key)
            return
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if rgb.shape != (self.config.height, self.config.width, 3):
            logger.error("Rejected %s shape %s; expected (%d, %d, 3)", key, rgb.shape,
                         self.config.height, self.config.width)
            return
        with self._lock:
            self._images[key] = rgb
            # Count decode time against image freshness instead of making an
            # old frame look newly received after expensive processing.
            self._image_times[key] = received_at

    def _assert_control_safe(self) -> dict[str, float]:
        now = time.monotonic()
        command_conflict = self._command_conflict_reason()
        if command_conflict:
            raise RuntimeError(command_conflict)
        latched_fault = self._dxl_health.latched_fault_reason(now)
        if latched_fault:
            raise RuntimeError(latched_fault)
        arrival_fault = self._dxl_health.arrival_fault_reason(now)
        if arrival_fault:
            raise RuntimeError(arrival_fault)
        arrival_stale = self._dxl_health.arrival_stale_reason(now)
        if arrival_stale:
            raise RecoverableDxlArrivalStale(arrival_stale)
        with self._lock:
            ages = {"joint_states": now - self._joint_time}
            ages.update({key: now - self._image_times.get(key, 0.0) for key in ("camera1", "camera2")})
        if ages["joint_states"] > self.config.joint_fault_timeout_s:
            raise RuntimeError(
                "ROS joint input terminally stale, refusing control: "
                f"{{'joint_states': {ages['joint_states']}}}"
            )
        if ages["joint_states"] > self.config.joint_stale_timeout_s:
            raise TransientInputFreshnessError(
                "Stale ROS joint input, temporarily holding control: "
                f"{{'joint_states': {ages['joint_states']}}}"
            )
        faulted_cameras = {
            key: ages[key]
            for key in ("camera1", "camera2")
            if ages[key] > self.config.camera_fault_timeout_s
        }
        if faulted_cameras:
            raise RuntimeError(
                "ROS camera input terminally stale, refusing control: "
                f"{faulted_cameras}"
            )
        stale_cameras = {
            key: ages[key]
            for key in ("camera1", "camera2")
            if ages[key] > self.config.camera_stale_timeout_s
        }
        if stale_cameras:
            raise TransientInputFreshnessError(
                f"Stale ROS camera input(s), refusing inference/control: {stale_cameras}"
            )
        return ages

    def wait_for_control_ready(self) -> bool:
        """Pause before queue pop during bounded input-freshness recovery.

        Returns True when a pause occurred, requiring the caller to discard the
        old action queue and request a new chunk from a fresh observation.
        """
        paused = False
        while True:
            try:
                self._assert_control_safe()
                generation = self._dxl_health.resync_generation()
                if generation != self._last_dxl_resync_generation:
                    self._last_dxl_resync_generation = generation
                    paused = True
                return paused
            except TransientInputFreshnessError:
                paused = True
                time.sleep(0.005)

    def _assert_observation_ready(self) -> None:
        now = time.monotonic()
        ages = self._assert_control_safe()
        receive_times = [now - age for age in ages.values()]
        skew = max(receive_times) - min(receive_times)
        if skew > self.config.max_sensor_skew_s:
            raise TransientInputFreshnessError(
                f"ROS sensor receive-time skew {skew:.4f}s exceeds {self.config.max_sensor_skew_s:.4f}s"
            )

    def get_observation(self) -> RobotObservation:
        if not self._connected:
            raise RuntimeError("ROS 2 OMX adapter is not connected")
        if self._first_observation_pending:
            deadline = time.monotonic() + self.config.startup_freshness_wait_s
            while True:
                try:
                    self._assert_observation_ready()
                    break
                except TransientInputFreshnessError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            self._first_observation_pending = False
        else:
            self._assert_observation_ready()
        with self._lock:
            assert self._joint_positions is not None
            obs: RobotObservation = {
                **{f"{name}.pos": self._joint_positions[name] for name in JOINT_NAMES},
                "camera1": self._images["camera1"].copy(),
                "camera2": self._images["camera2"].copy(),
            }
        return obs

    def send_action(self, action: RobotAction) -> RobotAction:
        with self._command_lock:
            if self._safe_stop_done:
                raise RuntimeError("Safe stop is latched; refusing further actions")
            return self._send_action_locked(action)

    def _warn_state_support_violations(
        self, positions: dict[str, float], *, context: str
    ) -> dict[str, dict[str, float]]:
        if not self._state_limits:
            return {}
        violations = absolute_limit_violations(
            positions,
            self._state_limits,
            self.config.absolute_state_tolerance_rad,
        )
        now = time.monotonic()
        if violations and now - self._last_state_support_warning_at >= 2.0:
            logger.warning(
                "Measured state outside empirical training-support envelope "
                "(%s); continuing under action, relative-step, freshness, and "
                "DYNAMIXEL guards: %s",
                context,
                violations,
            )
            self._last_state_support_warning_at = now
        return violations

    def _send_action_locked(self, action: RobotAction) -> RobotAction:
        if not self._connected:
            raise RuntimeError("ROS 2 OMX adapter is not connected")
        expected = tuple(self.action_features)
        if tuple(action) != expected:
            raise ValueError(f"Action keys/order mismatch: expected {expected}, got {tuple(action)}")
        values = [float(action[key]) for key in expected]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Action contains non-finite values")
        raw_action_values = list(values)

        if self._action_limits:
            tolerance = self.config.absolute_action_saturation_tolerance_rad
            violations = {
                name: value for name, value in zip(JOINT_NAMES, values, strict=True)
                if not self._action_limits[name][0] - tolerance
                <= value
                <= self._action_limits[name][1] + tolerance
            }
            if violations:
                self.safe_stop(f"absolute joint limit violation: {violations}")
                raise RuntimeError(
                    "Action outside audited absolute limits and saturation tolerance: "
                    f"{violations}"
                )
            raw_values = list(values)
            values = [
                max(self._action_limits[name][0], min(self._action_limits[name][1], value))
                for name, value in zip(JOINT_NAMES, values, strict=True)
            ]
            saturated = {
                name: {"requested": requested, "sent": sent}
                for name, requested, sent in zip(JOINT_NAMES, raw_values, values, strict=True)
                if abs(requested - sent) > 1e-9
            }
            if saturated:
                self._absolute_saturation_count += 1
                if (
                    self._absolute_saturation_count == 1
                    or self._absolute_saturation_count % 30 == 0
                ):
                    logger.warning(
                        "Absolute boundary saturation within audited tolerance "
                        "(count=%d): %s",
                        self._absolute_saturation_count,
                        saturated,
                    )
            else:
                self._absolute_saturation_count = 0

        # The converted demonstrations are strongly bimodal at the gripper:
        # close/hold commands occupy roughly 0.134--0.25 rad while deliberate
        # opening is concentrated around 0.65--0.75 rad. Preserve a recorded
        # strong-close target across the ambiguous middle band so overlapping
        # ACT chunks cannot relax the grasp during transport. Release still
        # comes from the learned policy and must be explicit for several
        # consecutive actions; this is not a timer or task-duration limit.
        if self.config.gripper_hold_enabled:
            policy_gripper = raw_action_values[-1]
            if not self._gripper_hold_latched:
                if policy_gripper <= self.config.gripper_close_enter_threshold_rad:
                    self._gripper_hold_latched = True
                    self._gripper_release_count = 0
                    logger.info(
                        "GRIPPER_HOLD_ENTER policy=%.6f target=%.6f",
                        policy_gripper,
                        self.config.gripper_hold_target_rad,
                    )
            elif policy_gripper >= self.config.gripper_open_release_threshold_rad:
                self._gripper_release_count += 1
                if self._gripper_release_count >= self.config.gripper_release_confirm_actions:
                    self._gripper_hold_latched = False
                    self._gripper_release_count = 0
                    logger.info("GRIPPER_HOLD_RELEASE policy=%.6f", policy_gripper)
            else:
                self._gripper_release_count = 0

            if self._gripper_hold_latched:
                values[-1] = self.config.gripper_hold_target_rad

        # Validate freshness/health immediately before taking the measured
        # state snapshot used for both OOD telemetry and relative limiting.
        # This avoids validating one callback sample and commanding from a
        # different one.
        self._assert_control_safe()
        with self._lock:
            assert self._joint_positions is not None
            measured_positions = dict(self._joint_positions)
        self._warn_state_support_violations(measured_positions, context="control")

        present = [measured_positions[name] for name in JOINT_NAMES]
        if self._first_action_pending:
            deltas_for_log = [
                requested - current
                for requested, current in zip(raw_action_values, present, strict=True)
            ]
            logger.info(
                "FIRST_RAW_ACTION joints=%s values=%s present=%s deltas=%s",
                list(JOINT_NAMES), raw_action_values, present, deltas_for_log,
            )
            self._first_action_pending = False

        if self.config.max_relative_target is not None:
            limits = [self.config.max_relative_target] * 5 + [
                self.config.max_gripper_relative_target or self.config.max_relative_target
            ]
            # Keep the five arm joints bounded relative to measured feedback.
            # For the gripper, only the first command is measured-relative;
            # subsequent commands slew from the last published target.  A
            # current-based-position gripper develops grasp force from the
            # target/feedback error after object contact. Re-anchoring the
            # target to feedback every cycle would erase that preload and was
            # inconsistent with the recorded training episodes, where the
            # close target remains below the stalled measured position for
            # several seconds.
            relative_bases = list(present)
            if self._last_commanded_positions is not None:
                relative_bases[-1] = self._last_commanded_positions[-1]
            unclipped = values
            values = [
                max(base - limit, min(base + limit, goal))
                for base, goal, limit in zip(relative_bases, values, limits, strict=True)
            ]
            clipped = {
                name: {
                    "requested": requested,
                    "sent": sent,
                    "basis": basis,
                    "basis_kind": (
                        "last_command" if name == "gripper_joint_1"
                        and self._last_commanded_positions is not None else "measured"
                    ),
                }
                for name, requested, sent, basis in zip(
                    JOINT_NAMES, unclipped, values, relative_bases, strict=True
                )
                if abs(requested - sent) > 1e-6
            }
            if clipped:
                self._consecutive_clamps += 1
                # Keep applying the bounded command instead of converting
                # normal task motion into a custom terminal fault. Absolute
                # action, DXL, freshness and non-finite guards remain terminal.
                if self._consecutive_clamps == 1 or self._consecutive_clamps % 30 == 0:
                    logger.warning(
                        "Relative action rate limiting active (count=%d): %s",
                        self._consecutive_clamps,
                        clipped,
                    )
            else:
                self._consecutive_clamps = 0

        # The measured-state limiter must never move the final command outside
        # the unchanged audited action envelope.  This can only happen when
        # feedback itself is already outside that envelope; refuse rather than
        # breaking either the absolute or per-step invariant.
        if self._action_limits:
            final_violations = {
                name: value
                for name, value in zip(JOINT_NAMES, values, strict=True)
                if not self._action_limits[name][0] <= value <= self._action_limits[name][1]
            }
            if final_violations:
                self.safe_stop(f"post-relative action limit violation: {final_violations}")
                raise RuntimeError(
                    "Measured-state relative limiting would publish outside the "
                    f"audited action envelope: {final_violations}"
                )

        self._gripper_command_count += 1
        if self._gripper_command_count == 1 or self._gripper_command_count % 30 == 0:
            logger.info(
                "GRIPPER_COMMAND count=%d policy=%.6f sent=%.6f measured=%.6f "
                "preload_error=%.6f slew_basis=%s",
                self._gripper_command_count,
                raw_action_values[-1],
                values[-1],
                present[-1],
                present[-1] - values[-1],
                (
                    "last_command"
                    if self._last_commanded_positions is not None else "measured"
                ),
            )

        msg = JointTrajectory()
        # ROS 2 JTC defines a zero header stamp as "start now". This avoids a
        # 33 ms one-point trajectory becoming old solely due to WSL scheduling.
        msg.joint_names = list(JOINT_NAMES)
        point = JointTrajectoryPoint()
        point.positions = values
        duration_ns = int(1e9 / self.config.fps)
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(duration_ns, 1_000_000_000)
        msg.points = [point]
        self._publisher.publish(msg)
        self._last_commanded_positions = list(values)
        return {key: value for key, value in zip(expected, values, strict=True)}

    def safe_stop(self, reason: str = "client shutdown") -> None:
        """Idempotently hold the latest measured pose and stop new commands.

        Torque is intentionally not disabled: an unsupported arm can fall. A
        physical emergency-stop remains required for real-hardware trials.
        """
        with self._command_lock:
            if self._safe_stop_done or not self._connected:
                return
            self._safe_stop_done = True
            logger.error("SAFE STOP: %s", reason)
            # Dry-run never moves hardware. Publishing a synthetic HOLD on the
            # analysis topic would be misclassified as a policy action.
            if self.config.dry_run:
                return
            # A DYNAMIXEL health fault means feedback is unavailable or the
            # actuator reported a hardware condition.  Publishing a cached
            # measured pose can command the arm backwards.  Stop publishing;
            # JTC retains its latest commanded point.
            stop_now = time.monotonic()
            if (
                self._dxl_health.latched_fault_reason(stop_now)
                or self._dxl_health.arrival_stale_reason(stop_now)
            ):
                logger.error("No additional HOLD trajectory published during DYNAMIXEL fault")
                return
            with self._lock:
                joint_age = time.monotonic() - self._joint_time
                if (
                    self._joint_positions is not None
                    and joint_age <= self.config.joint_stale_timeout_s
                ):
                    positions = [self._joint_positions[name] for name in JOINT_NAMES]
                elif self._last_commanded_positions is not None:
                    positions = list(self._last_commanded_positions)
                else:
                    return
            msg = JointTrajectory()
            # Zero stamp follows the JTC topic-interface "start now" contract.
            msg.joint_names = list(JOINT_NAMES)
            point = JointTrajectoryPoint()
            point.positions = positions
            duration_ns = int(1e9 / self.config.fps)
            point.time_from_start.sec, point.time_from_start.nanosec = divmod(
                duration_ns, 1_000_000_000
            )
            msg.points = [point]
            self._publisher.publish(msg)
            time.sleep(min(0.05, 1 / self.config.fps))

    def disconnect(self) -> None:
        if not self._connected and not hasattr(self, "_node"):
            return
        self.safe_stop("disconnect")
        self._connected = False
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=1.0)
        if self._spin_thread is not None and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=1.0)
        if hasattr(self, "_node"):
            self._node.destroy_node()
        if self._owns_rclpy and rclpy.ok():
            rclpy.shutdown()
