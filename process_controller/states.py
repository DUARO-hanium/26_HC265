"""
states.py — DUARO 공정 상태 정의 (PCS-01)

최종보고서 II.3 "공정 상태 기반 하이브리드 구조" 의 12개 상태를 그대로 사용한다.
각 상태는 타이머가 아니라 센서 입력과 로봇 상태(완료 이벤트)로만 전환된다.
"""
from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    IDLE = auto()                       # 대기
    PACKAGE_DETECTION = auto()          # 신규 패키지 존재, ROI 진입, 이전 Cycle 종료 확인
    PACKAGE_MANIPULATION = auto()       # 왼팔 Diffusion Policy: 개구부 확보·유지
    PRODUCT_EXTRACTION = auto()         # 오른팔 ACT: 내부 접근, 제품 파지, 인출
    WORKSPACE_SWITCHING = auto()        # 양팔 Safe Pose + Z Safe Height → 턴테이블 180°
    GARMENT_RECONFIGURATION = auto()    # FashionAI-SAM Grip Pair 승인, 미충족 시 재배치 루프
    FACE_A_INSPECTION = auto()          # Inspection Height 에서 Face A YOLO 검수
    SURFACE_SWITCHING = auto()          # Controlled Lay-down → 재관찰 → Re-grasp
    FACE_B_INSPECTION = auto()          # Face B YOLO 검수
    RESULT_INTEGRATION = auto()         # Face A/B 결과 통합 → 최종 판정
    SORTING = auto()                    # Sorting Height → 바구니 투입
    COMPLETED = auto()                  # 로그 저장, 다음 Cycle 대기
    ERROR = auto()                      # 복구 불가 예외. 사람 개입


# 공정별 Z축 목표 높이 이름 (실제 mm 값은 rdk/ 의 poses.csv 에서 Calibration 한 값을 쓴다)
class Height(str, Enum):
    PACKAGE = "package"
    MANIPULATION = "manipulation"
    INSPECTION = "inspection"
    SORTING = "sorting"
    SAFE = "safe"


# 각 상태에서 허용되는 다음 상태. 순서를 건너뛰는 전환은 막는다.
# 모든 운영 상태는 예외 시 ERROR 로 갈 수 있어야 한다 (Interlock 위반, 장치 실패, 카메라 타임아웃 등).
_OPERATIONAL: dict[State, tuple[State, ...]] = {
    State.IDLE: (State.PACKAGE_DETECTION,),
    State.PACKAGE_DETECTION: (State.PACKAGE_MANIPULATION, State.IDLE),
    State.PACKAGE_MANIPULATION: (State.PRODUCT_EXTRACTION, State.PACKAGE_MANIPULATION),
    State.PRODUCT_EXTRACTION: (State.WORKSPACE_SWITCHING, State.PACKAGE_MANIPULATION),
    State.WORKSPACE_SWITCHING: (State.GARMENT_RECONFIGURATION,),
    State.GARMENT_RECONFIGURATION: (State.FACE_A_INSPECTION, State.GARMENT_RECONFIGURATION, State.RESULT_INTEGRATION),
    State.FACE_A_INSPECTION: (State.SURFACE_SWITCHING,),
    State.SURFACE_SWITCHING: (State.FACE_B_INSPECTION, State.SURFACE_SWITCHING, State.RESULT_INTEGRATION),
    State.FACE_B_INSPECTION: (State.RESULT_INTEGRATION,),
    State.RESULT_INTEGRATION: (State.SORTING,),
    State.SORTING: (State.COMPLETED,),
    State.COMPLETED: (State.IDLE,),
    State.ERROR: (State.IDLE,),
}
TRANSITIONS: dict[State, tuple[State, ...]] = {
    s: (nxt if s in (State.IDLE, State.ERROR) else nxt + (State.ERROR,)) for s, nxt in _OPERATIONAL.items()
}
