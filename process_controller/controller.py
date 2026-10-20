"""
controller.py — DUARO Process Controller (PCS-01)

하나의 반품 패키지가 들어와 분류 바구니에 들어갈 때까지의 상태머신.
각 상태에서 하는 일은 "하위 모듈 호출 → 완료 조건 확인 → 다음 상태" 뿐이며,
AI 출력이 곧바로 액추에이터 명령이 되지 않도록 Interlock 과 Feasibility 검사를 사이에 둔다.

제작설계서 "핵심 소스코드 - 공정 상태 제어" 의 개념 코드를 실행 가능한 형태로 확장한 것이다.

    if state == PACKAGE_DETECT:
        if new_package and roi_ok and previous_cycle_done:
            state = PACKAGE_MANIPULATION
    elif state == PRODUCT_EXTRACTION:
        if extracted and arms_safe and z_safe:
            turntable.rotate_180()
            state = GARMENT_RECONFIGURATION
    elif state == GARMENT_RECONFIGURATION:
        grip_pair = validate(fashionai(), sam_mask())
        state = FACE_A if grip_pair.valid else RECONFIGURE
    elif state == SORTING:
        target_bin = integrate(face_a, face_b)
        z_axis.move(SORTING_HEIGHT)
        place_to(target_bin)

안전 규칙:
  * 모든 Z축 이동과 턴테이블 회전은 Interlock 검사를 거친 뒤 실행하고, 결과가 False 면 ProcessFault.
  * 어떤 예외든 run_once() 안에서 잡아 ERROR 상태로 보내고 양팔을 Safe Pose 로 되돌린다.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .interfaces import ArmMotion, ArmPolicy, AuxAxes, CycleLog, GraspVision, Inspector, Monitor
from .interlock import Interlock, InterlockViolation
from .states import TRANSITIONS, Height, State

log = logging.getLogger("duaro.pcs")

ADDITIONAL_INSPECTION = "추가 확인 필요"
RESELLABLE = "재판매 가능"


class ProcessFault(RuntimeError):
    """하위 모듈이 동작 실패(False)를 보고했거나 예외를 던진 경우."""


@dataclass
class ControllerConfig:
    max_reconfiguration: int = 3        # 재배치 반복 상한. 초과 시 추가 확인 필요로 분류
    max_policy_retry: int = 2           # 개구부/인출 한 상태 안에서의 재시도 횟수
    max_extraction_rounds: int = 2      # 인출 실패 → 개구부 재확보 로 돌아가는 횟수 상한 (사이클 전체)
    spread_ratio: float = 0.95          # d_target ≤ 0.95 W (Geometric Safety Constraint)
    settle_s: float = 1.0               # Z축/턴테이블 도달 후 안정화 대기
    log_dir: Path = Path("outputs/cycles")


class ProcessController:
    def __init__(
        self,
        policy: ArmPolicy,
        aux: AuxAxes,
        vision: GraspVision,
        motion: ArmMotion,
        inspector: Inspector,
        monitor: Monitor,
        config: ControllerConfig | None = None,
    ):
        self.policy, self.aux, self.vision, self.motion = policy, aux, vision, motion
        self.inspector, self.monitor = inspector, monitor
        self.cfg = config or ControllerConfig()
        self.interlock = Interlock()
        self.state = State.IDLE
        self.cycle_id = 0
        self.cycle: CycleLog | None = None
        self._extraction_complete = False
        self._extraction_rounds = 0
        self._result = None

    # ---- 상태 전환 ---------------------------------------------------------
    def _go(self, nxt: State, why: str = "") -> None:
        if nxt not in TRANSITIONS[self.state]:
            raise RuntimeError(f"허용되지 않은 전환 {self.state.name} → {nxt.name}")
        log.info("%s → %s %s", self.state.name, nxt.name, why)
        if self.cycle:
            self.cycle.events.append(f"{time.strftime('%H:%M:%S')} {self.state.name}->{nxt.name} {why}")
        self.state = nxt
        self.monitor.update(phase=nxt.name, note=why)

    # ---- 보조축 동작 (항상 Interlock → 실행 → 결과 확인) ------------------
    def _move_height(self, target: Height, phase_done: bool = True) -> None:
        self.interlock.check_height_change(phase_done=phase_done, arms=self.policy.pose())
        if not self.aux.move_height(target):
            raise ProcessFault(f"Z축 {target.value} 이동 실패")
        time.sleep(self.cfg.settle_s)
        if self.aux.current_height() != target:
            raise ProcessFault(f"Z축 {target.value} 도달 미확인 (현재 {self.aux.current_height()})")

    def _rotate_turntable(self) -> None:
        self._require(self.motion.go_safe_pose(), "Safe Pose 이동 실패")
        self._move_height(Height.SAFE)
        self.interlock.check_turntable(self._extraction_complete, self.policy.pose(), self.aux.current_height())
        if not self.aux.rotate_turntable_180():
            raise ProcessFault("턴테이블 회전 실패")
        time.sleep(self.cfg.settle_s)

    @staticmethod
    def _require(ok: bool, msg: str) -> None:
        if not ok:
            raise ProcessFault(msg)

    # ---- 메인 루프 ---------------------------------------------------------
    def run_once(self) -> CycleLog | None:
        """한 제품을 끝까지 처리하고 CycleLog 를 돌려준다. IDLE 에서 시작해 IDLE 로 돌아온다."""
        handlers = {
            State.IDLE: self._idle,
            State.PACKAGE_DETECTION: self._package_detection,
            State.PACKAGE_MANIPULATION: self._package_manipulation,
            State.PRODUCT_EXTRACTION: self._product_extraction,
            State.WORKSPACE_SWITCHING: self._workspace_switching,
            State.GARMENT_RECONFIGURATION: self._garment_reconfiguration,
            State.FACE_A_INSPECTION: self._face_a,
            State.SURFACE_SWITCHING: self._surface_switching,
            State.FACE_B_INSPECTION: self._face_b,
            State.RESULT_INTEGRATION: self._result_integration,
            State.SORTING: self._sorting,
            State.COMPLETED: self._completed,
            State.ERROR: self._error,
        }
        if self.state != State.IDLE:
            raise RuntimeError(f"run_once 는 IDLE 에서만 시작 (현재 {self.state.name})")
        self._go(State.PACKAGE_DETECTION, "cycle start")
        while self.state != State.IDLE:
            try:
                handlers[self.state]()
            except (InterlockViolation, ProcessFault) as e:
                self._fault(f"[{type(e).__name__}] {e}")
            except Exception as e:                      # 카메라 타임아웃, 추론 오류, 어댑터 예외 등
                log.exception("unexpected error in %s", self.state.name)
                self._fault(f"[{type(e).__name__}] {e}")
        return self.cycle

    def _fault(self, msg: str) -> None:
        log.error(msg)
        self.monitor.log(msg)
        if self.cycle:
            self.cycle.reason = self.cycle.reason or msg
        if self.state == State.ERROR:                   # ERROR 처리 중 또 실패하면 사람에게 넘기고 종료
            self._save_cycle_log()
            self.state = State.IDLE
            self.monitor.update(phase="IDLE", note="operator required")
            return
        self._go(State.ERROR, msg)

    # ---- 상태별 처리 -------------------------------------------------------
    def _idle(self) -> None:
        pass

    def _package_detection(self) -> None:
        self.cycle_id += 1
        self.cycle = CycleLog(self.cycle_id)
        self._extraction_complete = False
        self._extraction_rounds = 0
        self._result = None
        self.inspector.reset()
        self.monitor.update(cycle_id=self.cycle_id)

        obs = self.vision.observe_package()
        if not (obs.present and obs.in_roi and obs.stable):
            self.monitor.log("패키지 없음 또는 ROI 밖 / 불안정 → 대기")
            self.cycle = None
            self.cycle_id -= 1
            self._go(State.IDLE, "no stable package")
            return
        self._move_height(Height.PACKAGE)
        self._go(State.PACKAGE_MANIPULATION, "package stable in ROI")

    def _package_manipulation(self) -> None:
        for attempt in range(self.cfg.max_policy_retry + 1):
            if self.policy.run_left_opening():
                self.policy.hold_left()
                self._go(State.PRODUCT_EXTRACTION, f"opening ok (try {attempt + 1})")
                return
            self.monitor.log(f"Opening Failure {attempt + 1}")
        self.policy.release_all()
        raise ProcessFault("Opening Failure 반복")

    def _product_extraction(self) -> None:
        for attempt in range(self.cfg.max_policy_retry + 1):
            if self.policy.run_right_extraction():
                self._extraction_complete = True
                self.policy.release_all()
                self._go(State.WORKSPACE_SWITCHING, f"extracted (try {attempt + 1})")
                return
            self.monitor.log(f"Insertion/Grasp/Extraction Failure {attempt + 1}")
        self._extraction_rounds += 1
        if self._extraction_rounds >= self.cfg.max_extraction_rounds:
            self.policy.release_all()
            raise ProcessFault("Extraction Failure 반복 (개구부 재확보 상한 초과)")
        self._go(State.PACKAGE_MANIPULATION, f"extraction failed → re-open (round {self._extraction_rounds})")

    def _workspace_switching(self) -> None:
        self._rotate_turntable()
        self._move_height(Height.MANIPULATION)
        self._require(self.motion.place_on_table(), "작업대 내려놓기 실패")
        self._go(State.GARMENT_RECONFIGURATION, "turntable 180 done, garment on table")

    def _present_face(self, pair, next_state: State, why: str) -> None:
        """승인된 파지점으로 잡아 Inspection Height 에서 카메라에 전개."""
        self._move_height(Height.INSPECTION)
        self._require(
            self.motion.present_to_camera(max_spread_m=self.cfg.spread_ratio * pair.garment_width_m),
            "의류 전개 실패",
        )
        self._go(next_state, why)

    def _reconfigure_or_giveup(self, retry_state: State, why: str) -> None:
        if self.cycle.reconfiguration_count >= self.cfg.max_reconfiguration:
            self.monitor.log("재배치 상한 초과 → 추가 확인 필요")
            self._go(State.RESULT_INTEGRATION, "reconfiguration limit")
            return
        plan = self.vision.plan_reconfiguration()
        self._require(self.motion.reconfigure(plan), "재배치 동작 실패")
        self.cycle.reconfiguration_count += 1
        self.inspector.note_reconfiguration()
        self.monitor.update(reconfiguration_count=self.cycle.reconfiguration_count)
        self._go(retry_state, f"{why} ({plan.reason})")

    def _garment_reconfiguration(self) -> None:
        pair = self.vision.estimate_grip_pair()
        self.monitor.update(grip_reason=pair.reason)
        if pair.valid and self.motion.grasp_pair(pair):
            self._present_face(pair, State.FACE_A_INSPECTION, "inspection-ready grip pair")
            return
        if pair.valid:
            self.monitor.log("Grasp 실패 → 재배치")
        self._reconfigure_or_giveup(State.GARMENT_RECONFIGURATION, "reconfigured")

    def _face_a(self) -> None:
        self.interlock.check_inspection(self.aux.current_height(), self.policy.pose())
        res = self.inspector.inspect_face("A")
        self.monitor.update(face="A", face_result=res.to_dict())
        self._go(State.SURFACE_SWITCHING, "face A inspected")

    def _surface_switching(self) -> None:
        self._move_height(Height.MANIPULATION)
        self._require(self.motion.controlled_lay_down(), "Controlled Lay-down 실패")
        pair = self.vision.estimate_grip_pair()
        self.monitor.update(grip_reason=pair.reason)
        if pair.valid and self.motion.grasp_pair(pair):
            self._present_face(pair, State.FACE_B_INSPECTION, "re-grasped for face B")
            return
        self._reconfigure_or_giveup(State.SURFACE_SWITCHING, "reconfigured for face B")

    def _face_b(self) -> None:
        self.interlock.check_inspection(self.aux.current_height(), self.policy.pose())
        res = self.inspector.inspect_face("B")
        self.monitor.update(face="B", face_result=res.to_dict())
        self._go(State.RESULT_INTEGRATION, "face B inspected")

    def _result_integration(self) -> None:
        result = self.inspector.integrate()
        decision = result.decision.value
        reason = result.reason
        if decision not in (RESELLABLE, ADDITIONAL_INSPECTION):
            # Face A/B 를 모두 끝내지 못한 채 여기 온 경우 (재배치 상한 등) → 보수적으로 분류
            decision, reason = ADDITIONAL_INSPECTION, f"검수 미완료: {reason}"
        self._result = result
        self.cycle.decision, self.cycle.reason = decision, reason
        self.monitor.update(decision=decision, reason=reason)
        self._go(State.SORTING, decision)

    def _sorting(self) -> None:
        self.interlock.check_sorting(self.cycle.decision in (RESELLABLE, ADDITIONAL_INSPECTION))
        self._move_height(Height.SORTING)
        self._require(self.motion.drop_to_basket(resellable=self.cycle.decision == RESELLABLE), "바구니 투입 실패")
        self._require(self.motion.go_safe_pose(), "Safe Pose 이동 실패")
        self._go(State.COMPLETED, "placed to basket")

    def _completed(self) -> None:
        self._save_cycle_log()
        self._rotate_turntable()                     # Package Area 로 복귀 (Interlock 동일 적용)
        self._go(State.IDLE, "cycle complete")

    def _error(self) -> None:
        self.policy.release_all()
        self._require(self.motion.go_safe_pose(), "Safe Pose 복귀 실패: 수동 개입 필요")
        if self.cycle:
            self.cycle.decision = ADDITIONAL_INSPECTION
            self.cycle.reason = self.cycle.reason or "공정 예외"
            self._save_cycle_log()
        self._go(State.IDLE, "error → operator")

    # ---- 로그 --------------------------------------------------------------
    def _save_cycle_log(self) -> None:
        if not self.cycle:
            return
        self.cfg.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")      # 같은 초에 여러 사이클이 끝나도 덮어쓰지 않음
        path = self.cfg.log_dir / f"{stamp}_cycle{self.cycle_id:04d}.json"
        payload = {
            "cycle_id": self.cycle_id,
            "decision": self.cycle.decision,
            "reason": self.cycle.reason,
            "reconfiguration_count": self.cycle.reconfiguration_count,
            "extraction_rounds": self._extraction_rounds,
            "events": self.cycle.events,
            "result": self._result.to_dict() if self._result else None,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.monitor.log(f"cycle {self.cycle_id} saved → {path}")
