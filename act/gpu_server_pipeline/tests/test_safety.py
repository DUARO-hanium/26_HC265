import json
import threading
import time
from queue import Empty, Queue
from types import SimpleNamespace

import pytest
import grpc

from lerobot_robot_ros2_omx import Ros2Omx, Ros2OmxConfig
from lerobot_robot_ros2_omx.ros2_omx import (
    TransientInputFreshnessError,
    absolute_limit_violations,
    start_pose_violations,
)
from lerobot_robot_ros2_omx.safe_client import (
    SafeRobotClient,
    SafeRobotClientConfig,
    action_execution_gap_expired,
    chunk_stream_silence_expired,
    resync_admission_expired,
    update_queue_starvation,
)


JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")


def test_real_mode_is_fail_closed_without_confirmation():
    with pytest.raises(RuntimeError, match="confirmation"):
        Ros2Omx(Ros2OmxConfig(id="test", dry_run=False))


def test_real_mode_requires_complete_limits(tmp_path):
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps({name: {"min": -1, "max": 1} for name in JOINTS}))
    state_limits = tmp_path / "state_limits.json"
    state_limits.write_text(json.dumps({name: {"min": -2, "max": 2} for name in JOINTS}))
    start_pose = tmp_path / "start.json"
    start_pose.write_text(json.dumps({"positions": {name: 0.0 for name in JOINTS}}))
    robot = Ros2Omx(
        Ros2OmxConfig(
            id="test",
            dry_run=False,
            real_hardware_confirmation="I_UNDERSTAND_THIS_MOVES_OMX",
            safety_limits_path=str(limits),
            state_limits_path=str(state_limits),
            training_start_pose_path=str(start_pose),
            max_relative_target=0.05,
            max_gripper_relative_target=0.20,
        )
    )
    assert set(robot._action_limits) == set(JOINTS)
    assert set(robot._state_limits) == set(JOINTS)
    assert robot._state_limits["joint3"] == (-2.0, 2.0)


def test_real_start_pose_gate_reports_only_outside_joints():
    target = {name: 0.0 for name in JOINTS}
    current = dict(target)
    current["joint5"] = 0.09
    current["gripper_joint_1"] = 0.07
    violations = start_pose_violations(current, target, 0.08)
    assert set(violations) == {"joint5"}


def test_absolute_limit_gate_reports_boundary_violation():
    limits = {name: (-1.0, 1.0) for name in JOINTS}
    current = {name: 0.0 for name in JOINTS}
    current["joint3"] = 1.001
    violations = absolute_limit_violations(current, limits)
    assert set(violations) == {"joint3"}
    assert violations["joint3"]["max"] == 1.0
    assert absolute_limit_violations(current, limits, tolerance_rad=0.002) == {}


def test_queue_watchdog_only_expires_after_actual_starvation():
    empty_since, expired = update_queue_starvation(None, 1.0, False, 0.1)
    assert empty_since is None and not expired
    empty_since, expired = update_queue_starvation(None, 1.0, True, 0.1)
    assert empty_since == 1.0 and not expired
    empty_since, expired = update_queue_starvation(empty_since, 1.05, True, 0.1)
    assert not expired
    _, expired = update_queue_starvation(empty_since, 1.11, True, 0.1)
    assert expired


def test_queue_watchdog_is_suspended_during_dxl_resynchronization():
    empty_since, expired = update_queue_starvation(
        1.0, 2.0, True, 0.1, suspended=True
    )
    assert empty_since is None
    assert not expired


def test_queue_watchdog_is_suspended_while_refill_is_inflight():
    empty_since, expired = update_queue_starvation(
        1.0, 2.0, True, 0.1, suspended=True
    )
    assert empty_since is None
    assert not expired


def test_action_execution_gap_guard_is_first_action_exempt_and_fail_closed():
    assert not action_execution_gap_expired(None, 10.0, True, 0.12)
    assert not action_execution_gap_expired(10.0, 10.12, True, 0.12)
    assert action_execution_gap_expired(10.0, 10.120001, True, 0.12)
    assert action_execution_gap_expired(10.0, 10.499999, True, 0.12)
    assert action_execution_gap_expired(10.0, 10.5, True, 0.12)
    assert not action_execution_gap_expired(10.0, 10.5, False, 0.12)


def _bare_safe_client_for_resync():
    client = object.__new__(SafeRobotClient)
    client._action_dispatch_lock = threading.Lock()
    client.action_queue_lock = threading.Lock()
    client.action_queue = Queue()
    client.action_queue.put({"stale": True})
    client._observation_condition = threading.Condition()
    client._pending_observation = None
    client._observation_request_inflight = False
    client._observation_send_started_at = None
    client._observations_rejected_while_inflight = 0
    client._resync_required = False
    client._resync_request_sent = False
    client._resync_started_at = None
    client._last_chunk_received_at = None
    client.must_go = threading.Event()
    client._last_observation_not_ready_at = 0.0
    return client


@pytest.mark.parametrize("now", [10.55, 20.0])
def test_pure_local_action_gap_discards_stale_queue_without_terminal_fault(
    monkeypatch, now
):
    client = _bare_safe_client_for_resync()
    client.robot = SimpleNamespace()
    client.config = SimpleNamespace(max_action_execution_gap_s=0.12)
    client._last_action_executed_at = 10.0

    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.time.monotonic", lambda: now
    )

    assert SafeRobotClient.control_loop_action(client) == {}
    assert client.action_queue.empty()
    assert client._resync_required is True
    assert client._resync_request_sent is False
    assert client.must_go.is_set()


def test_transient_input_race_during_action_dispatch_forces_fresh_resync(monkeypatch):
    client = _bare_safe_client_for_resync()
    client.robot = SimpleNamespace()
    client.config = SimpleNamespace(
        max_action_execution_gap_s=0.12,
        max_executed_actions=None,
    )
    client._last_action_executed_at = None
    client._executed_actions = 0

    def transient_dispatch(_client, _verbose=False):
        raise TransientInputFreshnessError("camera1 age 0.264")

    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.RobotClient.control_loop_action",
        transient_dispatch,
    )

    assert SafeRobotClient.control_loop_action(client) == {}
    assert client.action_queue.empty()
    assert client._resync_required is True
    assert client.must_go.is_set()


def test_queue_empty_dispatch_race_resynchronizes_without_process_error(monkeypatch):
    client = _bare_safe_client_for_resync()
    client.robot = SimpleNamespace()
    client.config = SimpleNamespace(
        max_action_execution_gap_s=0.12,
        max_executed_actions=None,
    )
    client._last_action_executed_at = None
    client._executed_actions = 0

    def emptied_during_dispatch(_client, _verbose=False):
        raise Empty

    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.RobotClient.control_loop_action",
        emptied_during_dispatch,
    )
    assert SafeRobotClient.control_loop_action(client) == {}
    assert client._resync_required is True
    assert client.must_go.is_set()


def test_resync_waits_for_in_progress_action_dispatch(monkeypatch):
    client = _bare_safe_client_for_resync()
    client.robot = SimpleNamespace()
    client.config = SimpleNamespace(
        max_action_execution_gap_s=0.12,
        max_executed_actions=None,
    )
    client._last_action_executed_at = None
    client._executed_actions = 0
    dispatch_entered = threading.Event()
    allow_dispatch_return = threading.Event()
    resync_finished = threading.Event()

    def delayed_dispatch(_client, _verbose=False):
        dispatch_entered.set()
        assert allow_dispatch_return.wait(timeout=1.0)
        return {"joint1.pos": 0.0}

    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.RobotClient.control_loop_action",
        delayed_dispatch,
    )
    dispatch = threading.Thread(target=client.control_loop_action)
    dispatch.start()
    assert dispatch_entered.wait(timeout=1.0)

    def begin_resync():
        client._begin_stream_resynchronization("concurrent feedback gap")
        resync_finished.set()

    resync = threading.Thread(target=begin_resync)
    resync.start()
    assert not resync_finished.wait(timeout=0.05)
    allow_dispatch_return.set()
    dispatch.join(timeout=1.0)
    resync.join(timeout=1.0)
    assert resync_finished.is_set()
    assert client._resync_required is True
    assert client.action_queue.empty()


def test_grpc_transient_failure_resynchronizes_but_shutdown_is_terminal():
    client = _bare_safe_client_for_resync()
    client._stopping = False
    terminal_reasons = []
    client._trip_fault = terminal_reasons.append

    client._on_channel_state(grpc.ChannelConnectivity.TRANSIENT_FAILURE)
    assert client._resync_required is True
    assert client.action_queue.empty()
    assert terminal_reasons == []

    client._on_channel_state(grpc.ChannelConnectivity.SHUTDOWN)
    assert terminal_reasons == ["gRPC channel state SHUTDOWN"]


def test_resync_discards_locally_pending_observation_and_reopens_admission():
    client = _bare_safe_client_for_resync()
    client._pending_observation = SimpleNamespace(must_go=False)
    client._observation_request_inflight = True
    client._observation_send_started_at = 1.0

    client._begin_stream_resynchronization("test soft gap")

    assert client.action_queue.empty()
    assert client._pending_observation is None
    assert client._observation_request_inflight is False
    assert client._observation_send_started_at is None
    assert client._resync_required is True
    assert client._resync_request_sent is False
    assert client.must_go.is_set()


def test_resync_retains_actually_on_wire_request_until_late_reply_is_discarded():
    client = _bare_safe_client_for_resync()
    client._pending_observation = None
    client._observation_request_inflight = True
    client._observation_send_started_at = 1.0

    client._begin_stream_resynchronization("test on-wire gap")

    assert client._observation_request_inflight is True
    assert client._observation_send_started_at == 1.0
    assert client._resync_required is True
    assert client._resync_request_sent is False


def test_queue_install_and_resync_begin_are_atomic(monkeypatch):
    client = _bare_safe_client_for_resync()
    client._fault_reason = None
    client._stopping = False
    client._last_chunk_rtt_s = None
    client._last_action_executed_at = 1.0
    install_entered = threading.Event()
    allow_install_return = threading.Event()
    resync_finished = threading.Event()

    def delayed_official_install(_client, incoming, aggregate_fn=None):
        install_entered.set()
        assert allow_install_return.wait(timeout=1.0)
        with _client.action_queue_lock:
            _client.action_queue = Queue()
            _client.action_queue.put(incoming[0])
        return None

    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.RobotClient._aggregate_action_queues",
        delayed_official_install,
    )

    receiver = threading.Thread(
        target=client._aggregate_action_queues,
        args=([{"old_reply": True}],),
    )
    receiver.start()
    assert install_entered.wait(timeout=1.0)

    def begin_resync():
        client._begin_stream_resynchronization("concurrent camera gap")
        resync_finished.set()

    resync = threading.Thread(target=begin_resync)
    resync.start()
    # begin must wait for the atomic decision/install section, then clear it.
    assert not resync_finished.wait(timeout=0.05)
    allow_install_return.set()
    receiver.join(timeout=1.0)
    resync.join(timeout=1.0)
    assert resync_finished.is_set()
    assert client._resync_required is True
    assert client.action_queue.empty()


def test_queue_empty_transient_observation_enters_idempotent_resync(monkeypatch):
    client = _bare_safe_client_for_resync()
    client.action_queue = Queue()
    client._last_chunk_received_at = 9.0
    client.robot = SimpleNamespace(
        get_observation=lambda: (_ for _ in ()).throw(
            TransientInputFreshnessError("camera1 age 0.264")
        )
    )
    times = iter((10.0, 10.0, 10.2))
    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.time.monotonic", lambda: next(times)
    )

    assert SafeRobotClient.control_loop_observation(client, "task") == {}
    started_at = client._resync_started_at
    assert client._resync_required is True
    assert client._resync_request_sent is False
    assert client.must_go.is_set()

    # A repeated camera-soft sample must not restart the bounded deadline.
    assert SafeRobotClient.control_loop_observation(client, "task") == {}
    assert client._resync_started_at == started_at
    _, expired = update_queue_starvation(
        1.0, 10.2, True, 0.1, suspended=client._resync_required
    )
    assert not expired


def test_queue_empty_transient_recovery_admits_fresh_resync_request(monkeypatch):
    client = _bare_safe_client_for_resync()
    client.action_queue = Queue()
    client._last_chunk_received_at = 9.0
    calls = 0

    def observation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TransientInputFreshnessError("camera1 soft stale")
        return {"joint1.pos": 0.0}

    client.robot = SimpleNamespace(get_observation=observation)
    client.latest_action_lock = threading.Lock()
    client.latest_action = 0
    client.config = SimpleNamespace(force_threshold_observation=False)
    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.time.monotonic", lambda: 10.0
    )
    monkeypatch.setattr(
        "lerobot_robot_ros2_omx.safe_client.time.time", lambda: 100.0
    )

    assert SafeRobotClient.control_loop_observation(client, "task") == {}
    recovered = SafeRobotClient.control_loop_observation(client, "task")
    assert recovered["task"] == "task"
    assert client._resync_required is True
    assert client._resync_request_sent is True
    assert client._pending_observation is not None
    assert client._pending_observation.must_go is True


def test_transient_observation_preserves_first_chunk_and_nonempty_queue_deadlines():
    client = _bare_safe_client_for_resync()
    client.robot = SimpleNamespace(
        get_observation=lambda: (_ for _ in ()).throw(
            TransientInputFreshnessError("camera soft stale")
        )
    )

    # Before the first chunk, first_action_timeout_s remains authoritative.
    client.action_queue = Queue()
    assert SafeRobotClient.control_loop_observation(client, "task") == {}
    assert client._resync_required is False

    # With actions available, the pre-pop control safety path owns recovery.
    client._last_chunk_received_at = 9.0
    client.action_queue.put({"still_valid_until_pre_pop_check": True})
    assert SafeRobotClient.control_loop_observation(client, "task") == {}
    assert client._resync_required is False
    assert not client.action_queue.empty()


def test_wait_for_control_ready_soft_recovery_and_hard_escalation(monkeypatch):
    recovering = object.__new__(Ros2Omx)
    recovery_calls = iter(
        (TransientInputFreshnessError("camera soft"), {"camera1": 0.01})
    )

    def recover_check():
        result = next(recovery_calls)
        if isinstance(result, Exception):
            raise result
        return result

    recovering._assert_control_safe = recover_check
    recovering._dxl_health = SimpleNamespace(resync_generation=lambda: 0)
    recovering._last_dxl_resync_generation = 0
    monkeypatch.setattr("lerobot_robot_ros2_omx.ros2_omx.time.sleep", lambda _: None)
    assert recovering.wait_for_control_ready() is True

    terminal = object.__new__(Ros2Omx)
    terminal._assert_control_safe = lambda: (_ for _ in ()).throw(
        RuntimeError("camera terminally stale")
    )
    terminal._dxl_health = SimpleNamespace(resync_generation=lambda: 0)
    terminal._last_dxl_resync_generation = 0
    with pytest.raises(RuntimeError, match="terminally stale"):
        terminal.wait_for_control_ready()


def test_fresh_resync_marker_is_set_atomically_when_observation_is_admitted():
    client = _bare_safe_client_for_resync()
    client._resync_required = True
    observation = SimpleNamespace(must_go=True)

    assert client._offer_observation(observation) is True

    assert client._pending_observation is observation
    assert client._observation_request_inflight is True
    assert client._resync_request_sent is True


def test_chunk_silence_yields_to_refill_and_resynchronization_deadlines():
    assert chunk_stream_silence_expired(10.0, 11.51, 1.50)
    assert not chunk_stream_silence_expired(
        10.0, 11.51, 1.50, refill_inflight=True
    )
    assert not chunk_stream_silence_expired(
        10.0, 11.51, 1.50, resync_required=True
    )


def test_resync_admission_has_a_separate_bounded_deadline():
    assert not resync_admission_expired(True, False, 10.0, 10.99, 1.0)
    assert resync_admission_expired(True, False, 10.0, 11.01, 1.0)
    assert not resync_admission_expired(True, True, 10.0, 12.0, 1.0)
    assert not resync_admission_expired(False, False, 10.0, 12.0, 1.0)


def test_chunk_silence_must_exceed_configured_chunk_duration():
    common = {
        "policy_type": "act",
        "pretrained_name_or_path": "/tmp/checkpoint",
        "robot": Ros2OmxConfig(id="test"),
        "actions_per_chunk": 30,
        "fps": 30,
    }
    assert SafeRobotClientConfig(**common).max_chunk_silence_s == 1.50
    assert SafeRobotClientConfig(**common).max_refill_rtt_s == 5.00
    with pytest.raises(ValueError, match="chunk duration"):
        SafeRobotClientConfig(**common, max_chunk_silence_s=0.90)
    with pytest.raises(ValueError, match="positive"):
        SafeRobotClientConfig(
            **common,
            max_action_execution_gap_s=0.12,
            max_action_execution_fault_gap_s=0.0,
        )


def test_invalid_fps_rejected():
    with pytest.raises(ValueError, match="fps"):
        Ros2OmxConfig(id="test", fps=0)


def test_camera_fault_timeout_must_exceed_soft_stale_timeout():
    with pytest.raises(ValueError, match="ROS timing limits"):
        Ros2OmxConfig(
            id="test",
            camera_stale_timeout_s=0.25,
            camera_fault_timeout_s=0.25,
        )


def test_joint_fault_timeout_must_exceed_soft_stale_timeout():
    with pytest.raises(ValueError, match="hard deadlines"):
        Ros2OmxConfig(
            id="test",
            joint_stale_timeout_s=0.15,
            joint_fault_timeout_s=0.15,
        )


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _Now:
    def to_msg(self):
        from builtin_interfaces.msg import Time

        return Time()


class _Clock:
    def now(self):
        return _Now()


class _Node:
    def get_clock(self):
        return _Clock()

    def count_publishers(self, _topic):
        return 0


def _ready_dry_run_robot():
    robot = Ros2Omx(
        Ros2OmxConfig(
            id="test",
            dry_run=True,
            max_relative_target=0.05,
            max_gripper_relative_target=0.20,
        )
    )
    robot._connected = True
    robot._node = _Node()
    robot._publisher = _Publisher()
    robot._joint_positions = {name: 0.0 for name in JOINTS}
    now = time.monotonic()
    robot._joint_time = now
    robot._image_times = {"camera1": now, "camera2": now}
    return robot


def test_dry_run_trajectory_preserves_order_and_uses_split_clamps():
    robot = _ready_dry_run_robot()
    requested = {
        "joint1.pos": 0.10,
        "joint2.pos": 0.04,
        "joint3.pos": 0.0,
        "joint4.pos": 0.0,
        "joint5.pos": 0.0,
        "gripper_joint_1.pos": 0.15,
    }
    sent = robot.send_action(requested)
    msg = robot._publisher.messages[-1]
    assert msg.joint_names == list(JOINTS)
    assert msg.header.stamp.sec == 0 and msg.header.stamp.nanosec == 0
    assert list(msg.points[0].positions) == pytest.approx([0.05, 0.04, 0, 0, 0, 0.15])
    assert list(sent.values()) == pytest.approx(msg.points[0].positions)
    assert msg.points[0].time_from_start.nanosec == 33_333_333


def test_relative_clamp_rate_limits_and_publishes_policy_target():
    robot = _ready_dry_run_robot()
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["joint1.pos"] = 0.10
    for _ in range(100):
        sent = robot.send_action(requested)
        assert sent["joint1.pos"] == pytest.approx(0.05)
    assert len(robot._publisher.messages) == 100
    assert robot._publisher.messages[-1].points[0].positions[0] == pytest.approx(0.05)
    assert robot._safe_stop_done is False


def test_small_absolute_overshoot_is_saturated_to_audited_boundary():
    robot = _ready_dry_run_robot()
    robot._action_limits = {name: (-1.0, 1.0) for name in JOINTS}
    robot.config.absolute_action_saturation_tolerance_rad = 0.005
    robot._joint_positions["joint3"] = 0.99
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["joint3.pos"] = 1.003
    sent = robot.send_action(requested)
    assert sent["joint3.pos"] == pytest.approx(1.0)
    assert robot._publisher.messages[-1].points[0].positions[2] == pytest.approx(1.0)


def test_large_absolute_overshoot_is_rejected_before_publish():
    robot = _ready_dry_run_robot()
    robot._action_limits = {name: (-1.0, 1.0) for name in JOINTS}
    robot.config.absolute_action_saturation_tolerance_rad = 0.005
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["joint3.pos"] = 1.006
    with pytest.raises(RuntimeError, match="saturation tolerance"):
        robot.send_action(requested)
    assert robot._publisher.messages == []


def test_repeated_absolute_saturations_remain_clamped_and_publish():
    robot = _ready_dry_run_robot()
    robot._action_limits = {name: (-1.0, 1.0) for name in JOINTS}
    robot.config.absolute_action_saturation_tolerance_rad = 0.005
    robot._joint_positions["joint3"] = 0.99
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["joint3.pos"] = 1.003
    for _ in range(10):
        sent = robot.send_action(requested)
        assert sent["joint3.pos"] == pytest.approx(1.0)
    assert len(robot._publisher.messages) == 10
    assert robot._safe_stop_done is False


def test_measured_state_outside_empirical_support_warns_and_still_publishes(caplog):
    robot = _ready_dry_run_robot()
    robot._action_limits = {name: (-3.0, 3.0) for name in JOINTS}
    robot._state_limits = {name: (-2.0, 2.0) for name in JOINTS}
    robot._joint_positions["joint3"] = 1.5
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    robot.send_action(requested)
    assert len(robot._publisher.messages) == 1

    robot._joint_positions["joint3"] = 2.01
    with caplog.at_level("WARNING"):
        robot.send_action(requested)
    assert len(robot._publisher.messages) == 2
    assert robot._safe_stop_done is False
    assert "outside empirical training-support envelope" in caplog.text


def test_post_relative_command_cannot_leave_action_envelope():
    robot = _ready_dry_run_robot()
    robot._action_limits = {name: (-1.0, 1.0) for name in JOINTS}
    robot._state_limits = {name: (-2.0, 2.0) for name in JOINTS}
    robot._joint_positions["joint3"] = 2.01
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    with pytest.raises(RuntimeError, match="outside the audited action envelope"):
        robot.send_action(requested)
    assert robot._publisher.messages == []


def test_real_gripper_support_crossing_remains_bounded_and_publishable():
    robot = _ready_dry_run_robot()
    robot.config.max_gripper_relative_target = 0.03
    robot._action_limits = {name: (-3.0, 3.0) for name in JOINTS}
    robot._action_limits["gripper_joint_1"] = (0.1325197263349171, 1.7272623733888988)
    robot._state_limits = {name: (-3.0, 3.0) for name in JOINTS}
    robot._state_limits["gripper_joint_1"] = (0.24867192345749096, 1.7195924476992016)
    robot._joint_positions["gripper_joint_1"] = 0.23776702212206757
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["gripper_joint_1.pos"] = 0.1325197263349171
    sent = robot.send_action(requested)
    assert sent["gripper_joint_1.pos"] == pytest.approx(0.20776702212206757)
    assert robot._publisher.messages[-1].points[0].positions[-1] == pytest.approx(
        0.20776702212206757
    )


def test_gripper_slew_reaches_and_holds_close_target_after_contact_stall():
    robot = _ready_dry_run_robot()
    robot._joint_positions["gripper_joint_1"] = 0.40
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["gripper_joint_1.pos"] = 0.14

    first = robot.send_action(requested)
    assert first["gripper_joint_1.pos"] == pytest.approx(0.20)

    # Simulate contact: measured feedback remains at 0.40. The limiter must
    # nevertheless reach the learned close target from the previous command.
    second = robot.send_action(requested)
    third = robot.send_action(requested)
    assert second["gripper_joint_1.pos"] == pytest.approx(0.14)
    assert third["gripper_joint_1.pos"] == pytest.approx(0.14)


def test_gripper_target_does_not_follow_external_opening_after_contact():
    robot = _ready_dry_run_robot()
    robot._joint_positions["gripper_joint_1"] = 0.40
    requested = {f"{name}.pos": 0.0 for name in JOINTS}
    requested["gripper_joint_1.pos"] = 0.14
    robot.send_action(requested)
    robot.send_action(requested)

    # External compliance/slip opens the measured gripper, but the learned
    # close target and therefore the position preload remain unchanged.
    robot._joint_positions["gripper_joint_1"] = 0.55
    sent = robot.send_action(requested)
    assert sent["gripper_joint_1.pos"] == pytest.approx(0.14)


def test_gripper_opening_is_still_slew_limited_from_last_command():
    robot = _ready_dry_run_robot()
    robot._joint_positions["gripper_joint_1"] = 0.40
    close = {f"{name}.pos": 0.0 for name in JOINTS}
    close["gripper_joint_1.pos"] = 0.14
    robot.send_action(close)
    robot.send_action(close)

    open_action = dict(close)
    open_action["gripper_joint_1.pos"] = 0.70
    first_open = robot.send_action(open_action)
    second_open = robot.send_action(open_action)
    third_open = robot.send_action(open_action)
    assert first_open["gripper_joint_1.pos"] == pytest.approx(0.34)
    assert second_open["gripper_joint_1.pos"] == pytest.approx(0.54)
    assert third_open["gripper_joint_1.pos"] == pytest.approx(0.70)


def test_gripper_hold_latches_recorded_close_target_through_middle_band():
    robot = _ready_dry_run_robot()
    robot.config.gripper_hold_enabled = True
    robot._joint_positions["gripper_joint_1"] = 0.40
    action = {f"{name}.pos": 0.0 for name in JOINTS}

    action["gripper_joint_1.pos"] = 0.20
    entered = robot.send_action(action)
    assert entered["gripper_joint_1.pos"] == pytest.approx(0.20)
    settled = robot.send_action(action)
    assert settled["gripper_joint_1.pos"] == pytest.approx(
        robot.config.gripper_hold_target_rad
    )

    action["gripper_joint_1.pos"] = 0.45
    for _ in range(10):
        held = robot.send_action(action)
        assert held["gripper_joint_1.pos"] == pytest.approx(
            robot.config.gripper_hold_target_rad
        )


def test_gripper_hold_requires_confirmed_policy_open_before_release():
    robot = _ready_dry_run_robot()
    robot.config.gripper_hold_enabled = True
    action = {f"{name}.pos": 0.0 for name in JOINTS}
    action["gripper_joint_1.pos"] = 0.20
    robot.send_action(action)

    action["gripper_joint_1.pos"] = 0.70
    for _ in range(robot.config.gripper_release_confirm_actions - 1):
        held = robot.send_action(action)
        assert held["gripper_joint_1.pos"] == pytest.approx(
            robot.config.gripper_hold_target_rad
        )
    released = robot.send_action(action)
    assert released["gripper_joint_1.pos"] == pytest.approx(
        robot.config.gripper_hold_target_rad + robot.config.max_gripper_relative_target
    )


def test_gripper_hold_is_disabled_for_generic_adapter_by_default():
    robot = _ready_dry_run_robot()
    action = {f"{name}.pos": 0.0 for name in JOINTS}
    action["gripper_joint_1.pos"] = 0.20
    sent = robot.send_action(action)
    assert sent["gripper_joint_1.pos"] == pytest.approx(0.20)


def test_gripper_hold_config_rejects_inverted_thresholds():
    with pytest.raises(ValueError, match="target <= close threshold < open threshold"):
        Ros2OmxConfig(
            id="test",
            gripper_close_enter_threshold_rad=0.70,
            gripper_open_release_threshold_rad=0.60,
        )


def test_action_key_order_mismatch_is_rejected():
    robot = _ready_dry_run_robot()
    reversed_action = {f"{name}.pos": 0.0 for name in reversed(JOINTS)}
    with pytest.raises(ValueError, match="keys/order mismatch"):
        robot.send_action(reversed_action)


def test_safe_stop_latches_and_blocks_later_action():
    robot = _ready_dry_run_robot()
    action = {f"{name}.pos": 0.0 for name in JOINTS}
    robot.safe_stop("test fault")
    assert len(robot._publisher.messages) == 0
    with pytest.raises(RuntimeError, match="latched"):
        robot.send_action(action)
    assert len(robot._publisher.messages) == 0


def test_camera_and_joint_staleness_are_independent():
    robot = _ready_dry_run_robot()
    now = time.monotonic()
    robot._joint_time = now - 0.10
    robot._image_times = {"camera1": now - 0.20, "camera2": now - 0.20}
    robot._assert_control_safe()

    robot._joint_time = time.monotonic() - 0.16
    with pytest.raises(TransientInputFreshnessError, match="joint_states"):
        robot._assert_control_safe()

    robot._joint_time = time.monotonic() - 0.51
    with pytest.raises(RuntimeError, match="terminally stale"):
        robot._assert_control_safe()


def test_competing_command_publisher_is_terminal():
    robot = _ready_dry_run_robot()
    robot._node.count_publishers = lambda _topic: 1
    with pytest.raises(RuntimeError, match="Competing command publisher"):
        robot._assert_control_safe()


def test_camera_short_staleness_is_recoverable():
    robot = _ready_dry_run_robot()
    now = time.monotonic()
    robot._joint_time = now
    robot._image_times = {"camera1": now - 0.31, "camera2": now - 0.31}
    with pytest.raises(TransientInputFreshnessError, match="camera1"):
        robot._assert_control_safe()


def test_camera_prolonged_staleness_remains_terminal():
    robot = _ready_dry_run_robot()
    now = time.monotonic()
    robot._joint_time = now
    robot._image_times = {"camera1": now - 0.76, "camera2": now}
    with pytest.raises(RuntimeError, match="terminally stale"):
        robot._assert_control_safe()


def test_sensor_skew_blocks_observation_but_not_queued_action_safety():
    robot = _ready_dry_run_robot()
    now = time.monotonic()
    robot._joint_time = now
    robot._image_times = {"camera1": now - 0.21, "camera2": now - 0.21}
    robot._assert_control_safe()
    with pytest.raises(RuntimeError, match="skew"):
        robot._assert_observation_ready()
