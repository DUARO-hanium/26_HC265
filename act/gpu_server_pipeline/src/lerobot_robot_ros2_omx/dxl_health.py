from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import threading


@dataclass(frozen=True)
class DxlHealthSnapshot:
    seen: bool
    age_s: float | None
    loss_fraction: float
    observed_slots: int
    hard_fault: str | None


def startup_snapshot_acceptable(
    snapshot: DxlHealthSnapshot,
    *,
    max_age_s: float,
    max_loss_fraction: float,
) -> bool:
    """Apply the same bounded-loss policy during startup as during control."""
    return (
        snapshot.seen
        and snapshot.hard_fault is None
        and snapshot.age_s is not None
        and snapshot.age_s <= max_age_s
        and snapshot.loss_fraction <= max_loss_fraction
    )


class DxlHealthMonitor:
    """Bounded-loss monitor for the DYNAMIXEL state stream.

    Source timestamps estimate missing hardware read cycles.  Monotonic local
    arrival time is kept separately for the stale-feedback safety deadline, so
    an executor scheduling pause is not mislabeled as hardware packet loss.
    This is live zero-order-hold accounting, not offline interpolation.
    """

    def __init__(
        self,
        *,
        nominal_rate_hz: float,
        window_s: float,
        source_gap_timeout_s: float,
        arrival_stale_timeout_s: float,
        arrival_fault_timeout_s: float,
        max_loss_fraction: float,
        min_slots: int,
    ) -> None:
        self.period_s = 1.0 / nominal_rate_hz
        self.window_s = window_s
        self.source_gap_timeout_s = source_gap_timeout_s
        self.arrival_stale_timeout_s = arrival_stale_timeout_s
        self.arrival_fault_timeout_s = arrival_fault_timeout_s
        self.max_loss_fraction = max_loss_fraction
        self.min_slots = min_slots
        self._lock = threading.Lock()
        self._last_arrival_time: float | None = None
        self._last_source_time: float | None = None
        self._max_source_time: float | None = None
        self._events: deque[tuple[float, int, int]] = deque()
        self._hard_fault: str | None = None
        # Monotonic generation for a recovered delivery gap.  A control-loop
        # poll can miss the stale interval entirely when the callback recovers
        # first, so the recovery must remain observable until consumed.
        self._resync_generation = 0

    def observe(
        self,
        now: float,
        *,
        source_time_s: float | None = None,
        comm_state: int,
        ids: tuple[int, ...],
        dxl_hw_state: tuple[int, ...],
    ) -> None:
        with self._lock:
            previous_arrival = self._last_arrival_time
            if (
                previous_arrival is not None
                and now - previous_arrival > self.arrival_stale_timeout_s
            ):
                self._resync_generation += 1
            if comm_state == -16:
                self._hard_fault = "DYNAMIXEL hardware error reported (comm_state=-16)"
            nonzero_hw = {
                dxl_id: state
                for dxl_id, state in zip(ids, dxl_hw_state, strict=False)
                if state != 0
            }
            if nonzero_hw:
                self._hard_fault = f"DYNAMIXEL hardware error status: {nonzero_hw}"
            if comm_state not in (0, -7, -11, -16):
                self._hard_fault = f"DYNAMIXEL non-recoverable communication state: {comm_state}"

            current_failed = comm_state in (-7, -11)
            skipped = 0
            if source_time_s is not None and source_time_s > 0.0:
                source_advances = (
                    self._max_source_time is None or source_time_s > self._max_source_time
                )
                if source_advances and self._last_source_time is not None:
                    source_dt = source_time_s - self._last_source_time
                    slots = max(1, math.floor(source_dt / self.period_s + 0.5))
                    skipped = slots - 1
                    if source_dt > self.source_gap_timeout_s:
                        self._hard_fault = (
                            f"DYNAMIXEL source feedback gap {source_dt:.3f}s "
                            f"> {self.source_gap_timeout_s:.3f}s"
                        )
                    self._last_source_time = source_time_s
                    self._max_source_time = source_time_s
                elif source_advances:
                    self._last_source_time = source_time_s
                    self._max_source_time = source_time_s
                else:
                    # A regressing source clock is an invalid transition. Drop
                    # continuity and let the next valid sample re-anchor.
                    self._last_source_time = None
            else:
                # A zero/missing stamp must not bridge two valid samples and
                # manufacture a source gap on the following callback.
                self._last_source_time = None
            self._last_arrival_time = now
            total_slots = skipped + 1
            lost_slots = skipped + int(current_failed)
            self._events.append((now, lost_slots, total_slots))
            self._prune(now)

    def resync_generation(self) -> int:
        """Return the persistent count of recovered soft-stale intervals."""
        with self._lock:
            return self._resync_generation

    def reset_nonhard_history(self) -> None:
        """Re-anchor inferred loss without clearing stale or hardware faults."""
        with self._lock:
            self._events.clear()
            self._last_source_time = None

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def snapshot(self, now: float) -> DxlHealthSnapshot:
        with self._lock:
            self._prune(now)
            lost = sum(event[1] for event in self._events)
            slots = sum(event[2] for event in self._events)
            fraction = lost / slots if slots else 0.0
            age = (
                None
                if self._last_arrival_time is None
                else max(0.0, now - self._last_arrival_time)
            )
            return DxlHealthSnapshot(
                seen=self._last_arrival_time is not None,
                age_s=age,
                loss_fraction=fraction,
                observed_slots=slots,
                hard_fault=self._hard_fault,
            )

    def latched_fault_reason(self, now: float) -> str | None:
        state = self.snapshot(now)
        if state.hard_fault:
            return state.hard_fault
        if (
            state.observed_slots >= self.min_slots
            and state.loss_fraction > self.max_loss_fraction
        ):
            return (
                f"DYNAMIXEL rolling loss {state.loss_fraction:.1%} "
                f"> {self.max_loss_fraction:.1%} over {state.observed_slots} cycles"
            )
        return None

    def arrival_stale_reason(self, now: float) -> str | None:
        state = self.snapshot(now)
        if (
            state.seen
            and state.age_s is not None
            and state.age_s > self.arrival_stale_timeout_s
        ):
            return (
                f"DYNAMIXEL feedback arrival stale for {state.age_s:.3f}s "
                f"> {self.arrival_stale_timeout_s:.3f}s"
            )
        return None

    def arrival_fault_reason(self, now: float) -> str | None:
        state = self.snapshot(now)
        if (
            state.seen
            and state.age_s is not None
            and state.age_s > self.arrival_fault_timeout_s
        ):
            return (
                f"DYNAMIXEL feedback arrival stalled for {state.age_s:.3f}s "
                f"> {self.arrival_fault_timeout_s:.3f}s"
            )
        return None

    def fault_reason(self, now: float) -> str | None:
        return self.latched_fault_reason(now) or self.arrival_fault_reason(now)

    def warning_reason(self, now: float, warn_loss_fraction: float) -> str | None:
        arrival_warning = self.arrival_stale_reason(now)
        if arrival_warning and not self.arrival_fault_reason(now):
            return arrival_warning
        state = self.snapshot(now)
        if (
            state.observed_slots >= self.min_slots
            and state.loss_fraction > warn_loss_fraction
            and state.loss_fraction <= self.max_loss_fraction
        ):
            return (
                f"DYNAMIXEL rolling source loss warning {state.loss_fraction:.1%} "
                f"> {warn_loss_fraction:.1%} over {state.observed_slots} cycles"
            )
        return None
