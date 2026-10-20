import pytest

from lerobot_robot_ros2_omx.dxl_health import (
    DxlHealthMonitor,
    DxlHealthSnapshot,
    startup_snapshot_acceptable,
)


def test_startup_uses_bounded_loss_instead_of_requiring_zero_loss():
    acceptable = DxlHealthSnapshot(
        seen=True,
        age_s=0.04,
        loss_fraction=0.11,
        observed_slots=63,
        hard_fault=None,
    )
    assert startup_snapshot_acceptable(
        acceptable, max_age_s=0.12, max_loss_fraction=0.20
    )
    assert not startup_snapshot_acceptable(
        acceptable, max_age_s=0.03, max_loss_fraction=0.20
    )
    assert not startup_snapshot_acceptable(
        acceptable, max_age_s=0.12, max_loss_fraction=0.10
    )
    faulted = DxlHealthSnapshot(
        seen=True,
        age_s=0.01,
        loss_fraction=0.0,
        observed_slots=60,
        hard_fault="hardware error",
    )
    assert not startup_snapshot_acceptable(
        faulted, max_age_s=0.12, max_loss_fraction=0.20
    )


def monitor():
    return DxlHealthMonitor(
        nominal_rate_hz=30,
        window_s=2.0,
        source_gap_timeout_s=0.50,
        arrival_stale_timeout_s=0.12,
        arrival_fault_timeout_s=0.50,
        max_loss_fraction=0.20,
        min_slots=60,
    )


def observe_ok(subject, now, source_time_s=None):
    subject.observe(
        now,
        source_time_s=now if source_time_s is None else source_time_s,
        comm_state=0,
        ids=(11, 12, 13, 14, 15, 16),
        dxl_hw_state=(0,) * 6,
    )


def test_one_missing_cycle_is_tolerated():
    subject = monitor()
    for index in range(25):
        step = index if index < 10 else index + 1
        observe_ok(subject, step / 30)
    assert subject.fault_reason(26 / 30) is None
    assert 0 < subject.snapshot(26 / 30).loss_fraction < 0.10


def test_three_consecutive_missing_cycles_trip_stale_hold():
    subject = monitor()
    observe_ok(subject, 1.0)
    assert "arrival stale" in subject.arrival_stale_reason(1.129)
    assert subject.fault_reason(1.129) is None
    reason = subject.fault_reason(1.501)
    assert reason is not None and "stalled" in reason


def test_excessive_rolling_loss_trips_but_eleven_percent_only_warns():
    low = monitor()
    for index in range(30):
        step = index if index < 15 else index + 1
        observe_ok(low, step / 30)
    assert low.fault_reason(31 / 30) is None

    warning = monitor()
    now = 0.0
    for index in range(54):
        step = 2 if index >= 47 else 1
        now += step / 30
        observe_ok(warning, now)
    assert warning.fault_reason(now) is None
    assert "warning" in warning.warning_reason(now, 0.10)

    high = monitor()
    now = 0.0
    for index in range(48):
        now += (2 if index % 3 == 0 else 1) / 30
        observe_ok(high, now)
    assert "rolling loss" in high.fault_reason(now)


def test_callback_pause_does_not_invent_source_loss():
    subject = monitor()
    arrival = 0.0
    source = 10.0
    for index in range(65):
        arrival += (0.267 if index == 30 else 1 / 30)
        source += 1 / 30
        observe_ok(subject, arrival, source)
    snapshot = subject.snapshot(arrival)
    assert snapshot.loss_fraction == 0.0
    assert subject.fault_reason(arrival) is None


def test_invalid_source_stamp_resynchronizes_without_inventing_loss():
    subject = monitor()
    arrival = 0.0
    for source in (10.0, 10.0 + 1 / 30, 0.0, 9.0, 10.0 + 4 / 30):
        arrival += 1 / 30
        observe_ok(subject, arrival, source)
    assert subject.snapshot(arrival).loss_fraction == 0.0


def test_old_loss_expires_from_rolling_window():
    subject = monitor()
    now = 0.0
    source = 10.0
    for index in range(130):
        step = 2 if index == 5 else 1
        now += step / 30
        source += step / 30
        observe_ok(subject, now, source)
    assert subject.snapshot(now).loss_fraction == 0.0


def test_nonhard_history_reset_reanchors_loss_but_preserves_hardware_fault():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    observe_ok(subject, 1.2, 10.2)
    assert subject.snapshot(1.2).loss_fraction > 0.0
    subject.reset_nonhard_history()
    assert subject.snapshot(1.2).loss_fraction == 0.0
    observe_ok(subject, 1.233, 10.233)
    assert subject.snapshot(1.233).loss_fraction == 0.0

    subject.observe(
        1.266,
        source_time_s=10.266,
        comm_state=-16,
        ids=(11, 12, 13, 14, 15, 16),
        dxl_hw_state=(0,) * 6,
    )
    subject.reset_nonhard_history()
    assert "hardware" in subject.fault_reason(1.266).lower()


def test_source_gap_over_stale_limit_is_immediate():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    observe_ok(subject, 1.501, 10.501)
    assert "source feedback gap" in subject.fault_reason(1.501)


def test_121ms_source_gap_is_counted_but_not_immediate_fatal():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    generation = subject.resync_generation()
    observe_ok(subject, 1.121, 10.121)
    assert subject.latched_fault_reason(1.121) is None
    assert subject.snapshot(1.121).loss_fraction > 0.0
    assert subject.resync_generation() == generation + 1


def test_167ms_source_gap_holds_and_resynchronizes_without_terminal_fault():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    observe_ok(subject, 1.167, 10.167)
    snapshot = subject.snapshot(1.167)
    assert subject.latched_fault_reason(1.167) is None
    assert snapshot.loss_fraction > 0.0
    assert subject.resync_generation() == 1


def test_recovered_arrival_gap_remains_visible_after_stream_is_fresh():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    observe_ok(subject, 1.136, 10.0 + 4 / 30)
    assert subject.arrival_stale_reason(1.136) is None
    assert subject.fault_reason(1.136) is None
    assert subject.resync_generation() == 1


def test_arrival_stale_recovers_without_latching():
    subject = monitor()
    observe_ok(subject, 1.0, 10.0)
    assert subject.arrival_stale_reason(1.129)
    observe_ok(subject, 1.13, 10.0 + 1 / 30)
    assert subject.arrival_stale_reason(1.13) is None
    assert subject.fault_reason(1.13) is None


def test_explicit_recoverable_comm_loss_is_counted():
    subject = monitor()
    for index in range(65):
        subject.observe(
            index / 30,
            source_time_s=10.0 + index / 30,
            comm_state=-7 if index == 62 else 0,
            ids=(11, 12, 13, 14, 15, 16),
            dxl_hw_state=(0,) * 6,
        )
    snapshot = subject.snapshot(64 / 30)
    assert snapshot.loss_fraction == pytest.approx(1 / snapshot.observed_slots)


@pytest.mark.parametrize("comm_state,hw", [(-16, (0,) * 6), (0, (1, 0, 0, 0, 0, 0))])
def test_hardware_fault_is_immediate(comm_state, hw):
    subject = monitor()
    subject.observe(
        1.0,
        source_time_s=1.0,
        comm_state=comm_state,
        ids=(11, 12, 13, 14, 15, 16),
        dxl_hw_state=hw,
    )
    assert "hardware" in subject.fault_reason(1.0).lower()
