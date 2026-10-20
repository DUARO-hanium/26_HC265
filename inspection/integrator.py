"""
integrator.py — Face A / Face B 검수 결과 통합 및 최종 판정

보고서 판정 규칙:
  * 양쪽 면 모두 검수 시야가 확보되고(valid) 기준 이상의 이상이 검출되지 않으면 → RESELLABLE
  * 이상이 검출되었거나, 결과가 불확실하거나, 정상 검수 상태를 확보하지 못했으면 → ADDITIONAL_INSPECTION
  * 자동 판정을 강제하지 않는 보수적 정책: 애매하면 추가 확인 필요로 보낸다 (False Negative 억제).

"불확실" 의 기준은 두 가지로 둔다.
  1) 어느 한 면이라도 valid=False (ROI 미확보)
  2) 검출은 됐지만 confidence 가 uncertain_band 안에 있어 명확히 결함이라고 보기 어려움
     → 이 경우도 정상으로 넘기지 않고 추가 확인 필요로 분류한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .inspector import InspectionResult


class FinalDecision(str, Enum):
    RESELLABLE = "재판매 가능"
    ADDITIONAL_INSPECTION = "추가 확인 필요"
    PENDING = "검수 진행 중"


@dataclass
class IntegratedResult:
    decision: FinalDecision
    reason: str
    face_a: InspectionResult | None
    face_b: InspectionResult | None
    reconfiguration_count: int = 0
    defect_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "reconfiguration_count": self.reconfiguration_count,
            "defect_summary": self.defect_summary,
            "face_a": self.face_a.to_dict() if self.face_a else None,
            "face_b": self.face_b.to_dict() if self.face_b else None,
        }


class ResultIntegrator:
    def __init__(self, defect_conf_threshold: float = 0.5, uncertain_band: tuple[float, float] = (0.35, 0.5)):
        lo, hi = uncertain_band
        if not (lo < hi <= defect_conf_threshold):
            raise ValueError("uncertain_band 는 (lo, hi) 이고 hi ≤ defect_conf_threshold 여야 함")
        self.defect_conf_threshold = defect_conf_threshold
        self.uncertain_band = uncertain_band
        self.results: dict[str, InspectionResult] = {}
        self.reconfiguration_count = 0

    @property
    def record_conf(self) -> float:
        """YoloInspector(record_conf=...) 에 넘길 값. 불확실 구간 하한까지 기록해야 판정이 가능하다."""
        return self.uncertain_band[0]

    def reset(self) -> None:
        self.results.clear()
        self.reconfiguration_count = 0

    def add(self, result: InspectionResult) -> None:
        self.results[result.side] = result

    def note_reconfiguration(self) -> None:
        self.reconfiguration_count += 1

    @property
    def both_done(self) -> bool:
        return "A" in self.results and "B" in self.results

    def integrate(self) -> IntegratedResult:
        a, b = self.results.get("A"), self.results.get("B")
        if not self.both_done:
            return IntegratedResult(FinalDecision.PENDING, "Face A/B 검수 미완료", a, b, self.reconfiguration_count)

        summary: dict[str, int] = {}
        for r in (a, b):
            for d in r.defects:
                summary[d.cls] = summary.get(d.cls, 0) + 1

        # 1) 검수 시야 미확보 → 추가 확인
        invalid = [r.side for r in (a, b) if not r.valid]
        if invalid:
            return IntegratedResult(
                FinalDecision.ADDITIONAL_INSPECTION,
                f"Face {', '.join(invalid)} 검수 시야 미확보",
                a, b, self.reconfiguration_count, summary,
            )

        # 2) 명확한 결함 → 추가 확인
        confirmed = [(r.side, d) for r in (a, b) for d in r.defects if d.confidence >= self.defect_conf_threshold]
        if confirmed:
            desc = ", ".join(f"Face {s} {d.cls_ko} {d.confidence:.2f}" for s, d in confirmed)
            return IntegratedResult(FinalDecision.ADDITIONAL_INSPECTION, f"이상 검출: {desc}", a, b,
                                    self.reconfiguration_count, summary)

        # 3) 애매한 검출 → 정상으로 확정하지 않고 추가 확인
        lo, hi = self.uncertain_band
        uncertain = [(r.side, d) for r in (a, b) for d in r.defects if lo <= d.confidence < hi]
        if uncertain:
            desc = ", ".join(f"Face {s} {d.cls_ko} {d.confidence:.2f}" for s, d in uncertain)
            return IntegratedResult(FinalDecision.ADDITIONAL_INSPECTION, f"판정 불확실: {desc}", a, b,
                                    self.reconfiguration_count, summary)

        return IntegratedResult(FinalDecision.RESELLABLE, "양면 이상 없음", a, b, self.reconfiguration_count, summary)
