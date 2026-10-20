"""
interfaces.py — Process Controller 가 호출하는 하위 모듈 인터페이스

각 Protocol 은 이 저장소의 실제 모듈에 대응한다.
  * ArmPolicy        → act/dualarm_inference (왼팔 DP / 오른팔 ACT 순차 추론)
  * AuxAxes          → rdk/ (z축 리프트 + 턴테이블)
  * GraspVision      → grasp/vision (FashionAI-SAM 파지점 + 재배치 후보)
  * ArmMotion        → grasp/motion (좌표 → 접근 → 하강 → 파지 → 들기)
  * Inspector        → inspection/ (YOLO Face A/B)
  * Monitor          → ui/ (Monitoring Layer, 읽기 전용)

컨트롤러는 "AI 출력 → 상태 검증 → 물리 실행 가능성 확인 → 실행" 순서만 강제하고
모터나 모델을 직접 다루지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .states import Height


@dataclass
class ArmPose:
    """양팔 상태 요약. 실제 값은 /joint_states 와 TF 에서 채운다."""
    at_safe_pose: bool
    stable: bool                 # 관절 속도 ≤ 임계값
    holding: bool                # 그리퍼가 무언가를 물고 있음


@dataclass
class GripPair:
    left_xyz: tuple[float, float, float]
    right_xyz: tuple[float, float, float]
    valid: bool
    reason: str                  # 승인/거부 이유. Web UI 자막으로 노출
    garment_width_m: float = 0.0 # SAM mask 기준 실제 유효 폭 W. 전개 상한 d_target ≤ 0.95W 에 사용


@dataclass
class ReconfigurationPlan:
    left_xyz: tuple[float, float, float]
    right_xyz: tuple[float, float, float]
    lift_dz: float = 0.03
    reason: str = ""


@dataclass
class PackageObservation:
    present: bool
    in_roi: bool
    stable: bool                 # 연속 프레임에서 위치 변화 없음


class ArmPolicy(Protocol):
    def run_left_opening(self) -> bool: ...            # 개구부 확보. True = Opening Width 확보
    def run_right_extraction(self) -> bool: ...        # 접근·파지·인출. True = 제품 완전 분리
    def hold_left(self) -> None: ...                   # 오른팔 동작 중 개구부 유지
    def release_all(self) -> None: ...
    def pose(self) -> ArmPose: ...


class AuxAxes(Protocol):
    def move_height(self, target: Height) -> bool: ...  # 도달 + 안정화 후 True
    def rotate_turntable_180(self) -> bool: ...
    def current_height(self) -> Height | None: ...


class GraspVision(Protocol):
    def observe_package(self) -> PackageObservation: ...
    def estimate_grip_pair(self) -> GripPair: ...
    def plan_reconfiguration(self) -> ReconfigurationPlan: ...


class ArmMotion(Protocol):
    def place_on_table(self) -> bool: ...
    def grasp_pair(self, pair: GripPair) -> bool: ...  # 양팔 접근·하강·파지·들기
    def present_to_camera(self, max_spread_m: float) -> bool: ...
    def reconfigure(self, plan: ReconfigurationPlan) -> bool: ...
    def controlled_lay_down(self) -> bool: ...
    def go_safe_pose(self) -> bool: ...
    def drop_to_basket(self, resellable: bool) -> bool: ...


class Inspector(Protocol):
    def inspect_face(self, side: str): ...             # → inspection.InspectionResult
    def integrate(self): ...                           # → inspection.IntegratedResult
    def reset(self) -> None: ...
    def note_reconfiguration(self) -> None: ...


class Monitor(Protocol):
    def update(self, **fields) -> None: ...
    def log(self, message: str) -> None: ...


@dataclass
class CycleLog:
    """한 제품 처리 이력 (LOG-01)."""
    cycle_id: int
    events: list[str] = field(default_factory=list)
    reconfiguration_count: int = 0
    decision: str = ""
    reason: str = ""
