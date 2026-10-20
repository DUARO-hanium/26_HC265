import logging
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue

import draccus
import grpc

from lerobot.async_inference.configs import RobotClientConfig
from lerobot.async_inference.helpers import RawObservation, TimedObservation
from lerobot.async_inference.robot_client import RobotClient
from lerobot.utils.import_utils import register_third_party_plugins

logger = logging.getLogger(__name__)

from .ros2_omx import RecoverableDxlArrivalStale, TransientInputFreshnessError


def update_queue_starvation(empty_since, now, queue_empty, grace_s, *, suspended=False):
    """Return (new_empty_since, expired) for a queue-underflow watchdog."""
    if suspended:
        return None, False
    if not queue_empty:
        return None, False
    empty_since = now if empty_since is None else empty_since
    return empty_since, now - empty_since > grace_s


def action_execution_gap_expired(last_executed_at, now, actions_available, limit_s):
    """Detect a stale queued action before it is popped after a local loop stall."""
    return (
        actions_available
        and last_executed_at is not None
        and now - last_executed_at > limit_s
    )


def chunk_stream_silence_expired(
    last_chunk_at,
    now,
    limit_s,
    *,
    refill_inflight=False,
    resync_required=False,
):
    """Use chunk silence only when no fresher request already owns a deadline."""
    return (
        last_chunk_at is not None
        and not refill_inflight
        and not resync_required
        and now - last_chunk_at > limit_s
    )


def resync_admission_expired(required, request_sent, started_at, now, limit_s):
    """Bound the interval before a fresh post-gap observation is admitted."""
    return (
        required
        and not request_sent
        and started_at is not None
        and now - started_at > limit_s
    )


@dataclass
class SafeRobotClientConfig(RobotClientConfig):
    queue_empty_grace_s: float = 0.10
    first_action_timeout_s: float = 10.0
    max_chunk_silence_s: float = 1.50
    # Soft liveness threshold only. Official LeRobot does not terminally stop
    # on a slow observation RPC; an empty queue naturally means no new output.
    max_refill_rtt_s: float = 5.00
    max_action_execution_gap_s: float = 0.12
    # Backward-compatible CLI field.  A local action-thread scheduling gap is
    # not itself evidence of a hardware or network fault; stale queued work is
    # discarded below and the cause-specific DXL/RPC/sensor watchdogs decide
    # whether recovery is terminal.
    max_action_execution_fault_gap_s: float = 0.50
    # Task-specific compatibility override, not the stock RobotClient policy.
    # The launcher enables it explicitly for this slow, vision-driven task.
    force_threshold_observation: bool = False
    # Commissioning-only bound.  Count successfully published policy actions,
    # then publish a measured-pose HOLD and stop the client cleanly.
    max_executed_actions: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if (
            self.queue_empty_grace_s <= 0
            or self.first_action_timeout_s <= 0
            or self.max_chunk_silence_s <= 0
            or self.max_refill_rtt_s <= 0
            or self.max_action_execution_gap_s <= 0
        ):
            raise ValueError("Watchdog timeouts must be positive")
        if self.max_action_execution_fault_gap_s <= 0:
            raise ValueError("Watchdog timeouts must be positive")
        if self.max_executed_actions is not None and self.max_executed_actions <= 0:
            raise ValueError("max_executed_actions must be positive when configured")
        chunk_duration_s = self.actions_per_chunk / self.fps
        if self.max_chunk_silence_s <= chunk_duration_s:
            raise ValueError(
                "max_chunk_silence_s must exceed one configured action chunk duration "
                f"({chunk_duration_s:.3f}s)"
            )


class SafeRobotClient(RobotClient):
    """Official RobotClient with local health guards and recoverable liveness checks."""

    def __init__(self, config: SafeRobotClientConfig):
        super().__init__(config)
        self._client_started_at = time.monotonic()
        self._last_chunk_received_at: float | None = None
        self._queue_empty_since: float | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._observation_sender_thread: threading.Thread | None = None
        self._observation_condition = threading.Condition()
        self._pending_observation: TimedObservation | None = None
        self._observations_sent = 0
        self._observations_rejected_while_inflight = 0
        self._observation_request_inflight = False
        self._observation_send_started_at: float | None = None
        self._last_chunk_rtt_s: float | None = None
        self._fault_reason: str | None = None
        self._fault_lock = threading.Lock()
        # Serialize queue invalidation with pop+publish.  This closes both the
        # empty-queue TOCTOU and the one-stale-action-after-resync window in
        # the stock client's split actions_available()/get_nowait() path.
        self._action_dispatch_lock = threading.Lock()
        self._stopping = False
        self._last_health_warning_at = 0.0
        self._last_health_warning: str | None = None
        self._last_liveness_warning_at = 0.0
        self._last_liveness_warning: str | None = None
        self._last_observation_not_ready_at = 0.0
        self._resync_required = False
        self._resync_request_sent = False
        self._resync_started_at: float | None = None
        self._executed_actions = 0
        self._last_action_executed_at: float | None = None

    def _aggregate_action_queues(self, incoming_actions, aggregate_fn=None):
        if self._fault_reason is not None or self._stopping:
            logger.warning("Discarded action chunk after terminal stop")
            return super()._aggregate_action_queues([], aggregate_fn)
        fresh_resync_response = False
        previous = None
        now = None
        with self._observation_condition:
            if self._resync_required and not self._resync_request_sent:
                # This response belongs to an observation captured before the
                # DXL arrival pause. Discard it, then admit a fresh request.
                self._observation_request_inflight = False
                self._observation_send_started_at = None
                self._observation_condition.notify_all()
                logger.warning("Discarded pre-resynchronization action chunk")
                return super()._aggregate_action_queues([], aggregate_fn)
            if self._resync_required and self._resync_request_sent:
                if not incoming_actions:
                    # A filtered/empty reply is not a successful
                    # resynchronization. Admit another fresh must-go request.
                    self._observation_request_inflight = False
                    self._observation_send_started_at = None
                    self._resync_request_sent = False
                    self.must_go.set()
                    self._observation_condition.notify_all()
                    logger.warning("Empty resynchronization chunk; requesting another")
                    return super()._aggregate_action_queues([], aggregate_fn)
                fresh_resync_response = True
            # Keep the resynchronization decision and official queue install
            # atomic. Otherwise an old RPC reply can pass the check, pause,
            # and install stale work just after another thread begins resync.
            result = super()._aggregate_action_queues(incoming_actions, aggregate_fn)
            if incoming_actions:
                now = time.monotonic()
                previous = self._last_chunk_received_at
                self._last_chunk_received_at = now
                if self._observation_send_started_at is not None:
                    self._last_chunk_rtt_s = now - self._observation_send_started_at
                self._observation_request_inflight = False
                self._observation_send_started_at = None
                if fresh_resync_response:
                    self._resync_required = False
                    self._resync_request_sent = False
                    self._resync_started_at = None
                    # The next action belongs to a verified fresh generation,
                    # so the pre-gap timestamp must not label it stale.
                    self._last_action_executed_at = None
                self._observation_condition.notify_all()
        if incoming_actions:
            assert now is not None
            logger.info(
                "Action chunk received: size=%d interval_s=%s request_rtt_s=%s",
                len(incoming_actions),
                "first" if previous is None else f"{now - previous:.3f}",
                "unknown" if self._last_chunk_rtt_s is None else f"{self._last_chunk_rtt_s:.3f}",
            )
        return result

    def _begin_stream_resynchronization(self, reason: str) -> bool:
        """Drop pre-gap work once and require inference from a fresh observation.

        Returning False means another control path already started the same
        recovery.  Keeping the original start time prevents repeated 30 Hz
        transient observations from extending the admission deadline.
        """
        with self._action_dispatch_lock:
            with self._observation_condition:
                if self._resync_required:
                    return False
                # A locally pending observation has no RPC that could later clear
                # its inflight bookkeeping. If the sender already took it, retain
                # inflight so its late pre-resync response remains tracked and is
                # rejected by _aggregate_action_queues().
                if self._pending_observation is not None:
                    self._pending_observation = None
                    self._observation_request_inflight = False
                    self._observation_send_started_at = None
                self._resync_required = True
                self._resync_request_sent = False
                self._resync_started_at = time.monotonic()
            with self.action_queue_lock:
                self.action_queue = Queue()
        self.must_go.set()
        logger.warning(
            "%s; discarded old actions and requesting a fresh chunk",
            reason,
        )
        return True

    def control_loop_action(self, verbose: bool = False):
        if hasattr(self.robot, "wait_for_control_ready"):
            paused = self.robot.wait_for_control_ready()
            if paused:
                self._begin_stream_resynchronization(
                    "ROS input freshness recovered before terminal deadline"
                )
                return {}
        now = time.monotonic()
        with self.action_queue_lock:
            queued_action_available = not self.action_queue.empty()
        if action_execution_gap_expired(
            self._last_action_executed_at,
            now,
            queued_action_available,
            self.config.max_action_execution_gap_s,
        ):
            gap_s = now - self._last_action_executed_at
            reason = (
                f"local action execution gap {gap_s:.3f}s > "
                f"{self.config.max_action_execution_gap_s:.3f}s"
            )
            self._begin_stream_resynchronization(
                f"{reason}; stale queue refused and fresh inference required"
            )
            return {}
        try:
            with self._action_dispatch_lock:
                performed_action = super().control_loop_action(verbose)
            if performed_action:
                executed_at = time.monotonic()
                interval = (
                    None
                    if self._last_action_executed_at is None
                    else executed_at - self._last_action_executed_at
                )
                self._last_action_executed_at = executed_at
                self._executed_actions += 1
                # Per-action PTY logging can itself deschedule a 30 Hz Python
                # loop under WSL.  Keep first/periodic telemetry and surface
                # unusually slow intervals without flooding stdout.
                if (
                    self._executed_actions == 1
                    or self._executed_actions % 30 == 0
                    or (interval is not None and interval > self.config.max_action_execution_gap_s)
                ):
                    logger.info(
                        "Policy action executed: count=%d interval_s=%s",
                        self._executed_actions,
                        "first" if interval is None else f"{interval:.3f}",
                    )
            if performed_action and self.config.max_executed_actions is not None:
                if self._executed_actions >= self.config.max_executed_actions:
                    logger.warning(
                        "Supervised action limit reached: %d",
                        self.config.max_executed_actions,
                    )
                    if hasattr(self.robot, "safe_stop"):
                        self.robot.safe_stop("supervised action limit reached")
                    self.shutdown_event.set()
            return performed_action
        except Empty:
            self._begin_stream_resynchronization(
                "action queue changed during dispatch; requesting fresh inference"
            )
            return {}
        except TransientInputFreshnessError as exc:
            # An input can cross its soft-stale boundary after the pre-pop
            # check but before Robot.send_action(). No command was published;
            # discard the remaining generation and require fresh inference.
            self._begin_stream_resynchronization(
                f"ROS input became temporarily stale during action dispatch: {exc}"
            )
            return {}

    def start(self):
        ok = super().start()
        if ok:
            self._client_started_at = time.monotonic()
            self.channel.subscribe(self._on_channel_state, try_to_connect=True)
            self._observation_sender_thread = threading.Thread(
                target=self._observation_sender_loop, daemon=True
            )
            self._observation_sender_thread.start()
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()
        return ok

    def _offer_observation(self, observation: TimedObservation) -> bool:
        """Keep at most one not-yet-sent observation, preserving must-go work."""
        with self._observation_condition:
            if self._observation_request_inflight:
                self._observations_rejected_while_inflight += 1
                return False
            pending = self._pending_observation
            if pending is not None and pending.must_go and not observation.must_go:
                return False
            self._pending_observation = observation
            self._observation_request_inflight = True
            self._observation_send_started_at = time.monotonic()
            # Mark the accepted request as post-resync under the same lock.
            # This prevents a pre-resync observation from being mislabeled
            # fresh if resynchronization starts between two lock acquisitions.
            if self._resync_required:
                self._resync_request_sent = True
            self._observation_condition.notify()
            return True

    def control_loop_observation(self, task: str, verbose: bool = False) -> RawObservation:
        """Capture on the 30 Hz loop, but perform the blocking RPC off-loop.

        The wire object and official server remain unchanged. Coalescing avoids
        building an unbounded queue of two-camera observations on a slower VPN.
        """
        try:
            raw_observation: RawObservation = self.robot.get_observation()
        except TransientInputFreshnessError as exc:
            # This can happen exactly as a post-start chunk becomes empty.
            # Entering bounded resynchronization then suspends the 0.10 s
            # empty-queue watchdog until a fresh observation is admitted.
            # With queued work, control_loop_action owns the pause; before the
            # first chunk, the longer first-action startup deadline still owns
            # it. This avoids creating a stricter camera-triggered deadline.
            with self.action_queue_lock:
                queue_empty = self.action_queue.empty()
            if self._last_chunk_received_at is not None and queue_empty:
                self._begin_stream_resynchronization(
                    f"ROS observation temporarily stale before refill: {exc}"
                )
            now_monotonic = time.monotonic()
            if now_monotonic - self._last_observation_not_ready_at >= 1.0:
                logger.warning("Observation temporarily not ready; skipping refill: %s", exc)
                self._last_observation_not_ready_at = now_monotonic
            return {}
        raw_observation["task"] = task
        with self.latest_action_lock:
            latest_action = self.latest_action
        with self.action_queue_lock:
            queue_empty_must_go = self.must_go.is_set() and self.action_queue.empty()
        now = time.time()
        observation = TimedObservation(
            timestamp=now,
            observation=raw_observation,
            timestep=max(latest_action, 0),
        )
        # The stock server may filter a threshold observation when slow joint
        # motion has norm < 1 rad, even if the images changed.  The optional
        # override reuses the protocol's must_go field for each gated refill.
        # This is task-specific scheduling, not stock RobotClient semantics.
        observation.must_go = self.config.force_threshold_observation or queue_empty_must_go
        accepted = self._offer_observation(observation)
        if accepted and queue_empty_must_go:
            self.must_go.clear()
        return raw_observation

    def _observation_sender_loop(self) -> None:
        while self.running:
            with self._observation_condition:
                self._observation_condition.wait_for(
                    lambda: self._pending_observation is not None or not self.running,
                    timeout=0.1,
                )
                if not self.running:
                    return
                observation = self._pending_observation
                self._pending_observation = None
            if observation is not None:
                send_started = time.monotonic()
                if not self.send_observation(observation):
                    if not self._stopping:
                        # Official LeRobot logs an RpcError and keeps its
                        # control loop alive. Reopen admission, HOLD by sending
                        # no action, and require a fresh generation on recovery.
                        with self._observation_condition:
                            self._observation_request_inflight = False
                            self._observation_send_started_at = None
                            self._resync_request_sent = False
                            self._observation_condition.notify_all()
                        self._begin_stream_resynchronization(
                            "observation RPC failed transiently"
                        )
                    continue
                self._observations_sent += 1
                logger.info(
                    "Observation RPC complete: upload_s=%.3f sent=%d rejected_inflight=%d must_go=%s",
                    time.monotonic() - send_started,
                    self._observations_sent,
                    self._observations_rejected_while_inflight,
                    observation.must_go,
                )

    def _trip_fault(self, reason: str) -> None:
        with self._fault_lock:
            if self._fault_reason is not None or self._stopping:
                return
            self._fault_reason = reason
            with self.action_queue_lock:
                self.action_queue = Queue()
            if hasattr(self.robot, "safe_stop"):
                self.robot.safe_stop(reason)
            self.shutdown_event.set()
            logger.error("Latched inference fault: %s; process restart and re-arm required", reason)

    def _on_channel_state(self, state: grpc.ChannelConnectivity) -> None:
        if state == grpc.ChannelConnectivity.SHUTDOWN:
            self._trip_fault(f"gRPC channel state {state.name}")
        elif state == grpc.ChannelConnectivity.TRANSIENT_FAILURE and not self._stopping:
            self._begin_stream_resynchronization(
                "gRPC channel transient failure; holding until recovery"
            )

    def _warn_liveness(self, reason: str, now: float) -> None:
        if (
            reason != self._last_liveness_warning
            or now - self._last_liveness_warning_at >= 2.0
        ):
            logger.warning("%s; continuing in HOLD/resynchronization mode", reason)
            self._last_liveness_warning = reason
            self._last_liveness_warning_at = now

    def _watchdog_loop(self):
        last_watchdog_at: float | None = None
        while self.running:
            now = time.monotonic()
            # If the whole process was descheduled, let the ROS executor drain
            # already-queued sensor callbacks before deciding that DXL alone
            # went stale.  A real continuing dropout remains stale on the next
            # watchdog pass and still latches HOLD.
            if last_watchdog_at is not None and now - last_watchdog_at > 0.05:
                logger.warning("Watchdog scheduling pause: %.3fs", now - last_watchdog_at)
                last_watchdog_at = now
                time.sleep(0.02)
                continue
            last_watchdog_at = now
            if hasattr(self.robot, "health_fault_reason"):
                health_fault = self.robot.health_fault_reason()
                if health_fault:
                    self._trip_fault(health_fault)
                    return
            if hasattr(self.robot, "health_warning_reason"):
                health_warning = self.robot.health_warning_reason()
                if health_warning and (
                    health_warning != self._last_health_warning
                    or now - self._last_health_warning_at >= 2.0
                ):
                    logger.warning("%s", health_warning)
                    self._last_health_warning = health_warning
                    self._last_health_warning_at = now
            with self._observation_condition:
                send_started = self._observation_send_started_at
                resync_required = self._resync_required
                resync_request_sent = self._resync_request_sent
                resync_started_at = self._resync_started_at
            # The first request is governed by first_action_timeout_s so model
            # warm-up is not accidentally limited by the shorter refill RTT.
            if (
                self._last_chunk_received_at is not None
                and send_started is not None
                and (not resync_required or resync_request_sent)
                and now - send_started > self.config.max_refill_rtt_s
            ):
                self._begin_stream_resynchronization(
                    "observation-to-chunk refill RTT exceeded soft liveness threshold"
                )
                self._warn_liveness("slow observation-to-chunk refill", now)
                time.sleep(0.01)
                continue
            if resync_admission_expired(
                resync_required,
                resync_request_sent,
                resync_started_at,
                now,
                self.config.max_refill_rtt_s,
            ):
                self._warn_liveness("fresh observation admission is still pending", now)
            if self._last_chunk_received_at is None:
                expired = now - self._client_started_at > self.config.first_action_timeout_s
                reason = "first action chunk timeout"
            else:
                if chunk_stream_silence_expired(
                    self._last_chunk_received_at,
                    now,
                    self.config.max_chunk_silence_s,
                    refill_inflight=send_started is not None,
                    resync_required=resync_required,
                ):
                    self._begin_stream_resynchronization(
                        "action chunk stream exceeded soft silence threshold"
                    )
                    self._warn_liveness("action chunk stream is still silent", now)
                    time.sleep(0.01)
                    continue
                with self.action_queue_lock:
                    queue_empty = self.action_queue.empty()
                self._queue_empty_since, expired = update_queue_starvation(
                    self._queue_empty_since,
                    now,
                    queue_empty,
                    self.config.queue_empty_grace_s,
                    suspended=resync_required or send_started is not None,
                )
                reason = "action queue starvation"
            if expired:
                if reason == "action queue starvation":
                    self._begin_stream_resynchronization(
                        "action queue empty beyond soft grace period"
                    )
                self._warn_liveness(reason, now)
                if reason == "first action chunk timeout":
                    # Reject a late reply based on the old first observation;
                    # remain safely stationary and request a fresh generation.
                    self._begin_stream_resynchronization(
                        "first action chunk exceeded soft startup threshold"
                    )
                    self._client_started_at = now
            time.sleep(0.01)

    def stop(self):
        self._stopping = True
        with self._observation_condition:
            self._observation_condition.notify_all()
        super().stop()
        if self._observation_sender_thread is not None and self._observation_sender_thread.is_alive():
            self._observation_sender_thread.join(timeout=1.0)
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.0)


@draccus.wrap()
def safe_async_client(cfg: SafeRobotClientConfig):
    client = SafeRobotClient(cfg)
    if not client.start():
        client.stop()
        raise RuntimeError("Failed to start official LeRobot policy client")
    action_receiver = threading.Thread(target=client.receive_actions, daemon=True)
    action_receiver.start()
    try:
        client.control_loop(task=cfg.task)
        if client._fault_reason:
            raise RuntimeError(client._fault_reason)
    finally:
        client.stop()
        action_receiver.join(timeout=1.0)


def main():
    register_third_party_plugins()
    safe_async_client()


if __name__ == "__main__":
    main()
