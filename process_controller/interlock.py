"""
interlock.py — Z축, 턴테이블, 양팔 사이의 S/W Interlock

최종보고서 II.3 "Z축, 턴테이블, 양팔 간 S/W Interlock" 의 허용 조건표를 코드로 옮긴 것.

| 동작             | 허용 조건                                        | 금지 조건                     |
|------------------|--------------------------------------------------|-------------------------------|
| Turntable 180°   | Extraction Complete, 양팔 Safe Pose, Z Safe      | 양팔이 작업대 방향으로 전개   |
| Z축 Height 변경  | 해당 공정 종료, Arm Stable                        | 파지 직후 동적 Manipulation 중 |
| Face Inspection  | Inspection Height 도달, 영상 안정                 | Z축 이동 중                   |
| Sorting          | Face A/B 결과 통합 완료                           | 검수 결과 미확정              |
"""
from __future__ import annotations

from .interfaces import ArmPose
from .states import Height


class InterlockViolation(RuntimeError):
    pass


class Interlock:
    def __init__(self, allow_turntable_while_holding: bool = True):
        # 인출된 제품을 든 채로 회전하는 것은 설계상 허용 (Safe Pose 이기만 하면 됨)
        self.allow_turntable_while_holding = allow_turntable_while_holding

    def check_turntable(self, extraction_complete: bool, arms: ArmPose, height: Height | None) -> None:
        if not extraction_complete:
            raise InterlockViolation("턴테이블 회전 금지: 제품 인출 미완료")
        if not arms.at_safe_pose:
            raise InterlockViolation("턴테이블 회전 금지: 양팔이 Safe Pose 가 아님")
        if height != Height.SAFE:
            raise InterlockViolation(f"턴테이블 회전 금지: Z축이 Safe Height 가 아님 (현재 {height})")
        if arms.holding and not self.allow_turntable_while_holding:
            raise InterlockViolation("턴테이블 회전 금지: 파지 상태")

    def check_height_change(self, phase_done: bool, arms: ArmPose) -> None:
        if not phase_done:
            raise InterlockViolation("Z축 이동 금지: 현재 공정 미종료")
        if not arms.stable:
            raise InterlockViolation("Z축 이동 금지: 팔이 동작 중")

    def check_inspection(self, height: Height | None, arms: ArmPose) -> None:
        if height != Height.INSPECTION:
            raise InterlockViolation(f"검수 금지: Inspection Height 미도달 (현재 {height})")
        if not arms.stable:
            raise InterlockViolation("검수 금지: 영상이 안정되지 않음 (팔 동작 중)")

    def check_sorting(self, result_integrated: bool) -> None:
        if not result_integrated:
            raise InterlockViolation("분류 금지: Face A/B 결과 미통합")
