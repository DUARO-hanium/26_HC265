"""
inspector.py — YOLO 기반 외관 이상 검수 (INS-01)

정면 Inspection Camera(ESP32-S3-CAM) 영상 한 장을 받아 이염 / 얼룩 / 찢김을 검출한다.
Face A와 Face B를 각각 한 번씩 호출하고, 두 결과는 integrator.py 에서 통합한다.

설계 기준 (최종보고서 II.3 "YOLO 기반 외관 이상 검수 모델"):
  * 출력: 이상 영역의 bbox, class, confidence
  * passed 는 "검출된 이상이 없음" 으로만 정의한다. 불확실한 경우의 처리는 integrator 가 담당.
  * 검수 시야가 충분히 확보되지 않은 프레임(ROI 미확보)은 passed=False 가 아니라 valid=False 로
    표시해 "추가 확인 필요" 경로로 보낸다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

import numpy as np

Side = Literal["A", "B"]

DEFAULT_CLASSES = ("stain", "discoloration", "tear")   # 얼룩 / 이염 / 찢김
CLASS_KO = {"stain": "얼룩", "discoloration": "이염", "tear": "찢김"}


@dataclass
class Defect:
    cls: str
    confidence: float
    bbox: list[float]            # [x1, y1, x2, y2] pixel

    @property
    def cls_ko(self) -> str:
        return CLASS_KO.get(self.cls, self.cls)


@dataclass
class InspectionResult:
    side: Side
    passed: bool                 # record_conf 이상의 검출 0건 (불확실 검출도 포함해 0건이어야 True)
    valid: bool                  # 검수 가능한 프레임이었는가 (ROI 안에 의류가 충분히 들어왔는가)
    defects: list[Defect] = field(default_factory=list)
    frame_shape: tuple[int, int] = (0, 0)
    garment_area_ratio: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def max_confidence(self) -> float:
        return max((d.confidence for d in self.defects), default=0.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["max_confidence"] = self.max_confidence
        return d


class YoloInspector:
    """ultralytics YOLO 가중치를 로드해 한 면을 검수한다."""

    def __init__(
        self,
        weights: str | Path,
        record_conf: float = 0.35,
        min_garment_area_ratio: float = 0.15,
        imgsz: int = 640,
        device: str | None = None,
    ):
        """record_conf: 이 값 이상의 검출을 모두 결과에 남긴다.
        "결함 확정" 과 "불확실" 의 구분은 integrator 가 하므로, 여기서는 불확실 구간의 하한까지 내려서 기록해야 한다.
        (예: integrator 의 uncertain_band=(0.35, 0.5) 이면 record_conf=0.35)"""
        from ultralytics import YOLO   # 지연 import: 다른 모듈이 inspection 을 import 해도 무겁지 않게

        self.model = YOLO(str(weights))
        self.record_conf = record_conf
        self.min_garment_area_ratio = min_garment_area_ratio
        self.imgsz = imgsz
        self.device = device
        self.names: dict[int, str] = self.model.names

    # ---- 검수 시야 확보 여부 --------------------------------------------------
    def _garment_area_ratio(self, frame: np.ndarray) -> float:
        """어두운 배경 대비 밝은 전경(의류) 픽셀 비율의 단순 추정.
        정확한 segmentation 이 필요하면 grasp/vision 의 SAM mask 를 garment_mask 로 넘겨 대체한다."""
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, fg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return float((fg > 0).mean())

    # ---- 검수 --------------------------------------------------------------
    def inspect(self, frame: np.ndarray, side: Side, garment_mask: np.ndarray | None = None) -> InspectionResult:
        h, w = frame.shape[:2]
        if garment_mask is not None:
            area_ratio = float((garment_mask > 0).mean())
        else:
            area_ratio = self._garment_area_ratio(frame)
        valid = area_ratio >= self.min_garment_area_ratio

        result = self.model.predict(
            frame, conf=self.record_conf, imgsz=self.imgsz, device=self.device, verbose=False
        )[0]

        defects: list[Defect] = []
        for box in result.boxes:
            cls_id = int(box.cls[0])
            defects.append(
                Defect(
                    cls=self.names.get(cls_id, str(cls_id)),
                    confidence=float(box.conf[0]),
                    bbox=[float(v) for v in box.xyxy[0].tolist()],
                )
            )

        return InspectionResult(
            side=side,
            passed=len(defects) == 0,
            valid=valid,
            defects=defects,
            frame_shape=(h, w),
            garment_area_ratio=area_ratio,
        )


def draw_result(frame: np.ndarray, result: InspectionResult) -> np.ndarray:
    """Web UI / 저장용 오버레이. bbox + class + confidence."""
    import cv2

    out = frame.copy()
    for d in result.defects:
        x1, y1, x2, y2 = map(int, d.bbox)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(out, f"{d.cls} {d.confidence:.2f}", (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    status = "PASS" if result.passed else "DEFECT"
    roi_note = "" if result.valid else " (ROI not secured)"
    cv2.putText(out, f"Face {result.side}: {status}{roi_note}", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return out


def save_result(result: InspectionResult, out_dir: str | Path, frame: np.ndarray | None = None) -> Path:
    """Face 별 결과 JSON (+ 오버레이 이미지) 저장. 작업 이력 / LOG-01 입력."""
    import cv2

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = time.strftime("%Y%m%d_%H%M%S") + f"_face{result.side}"
    (out_dir / f"{stem}.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if frame is not None:
        cv2.imwrite(str(out_dir / f"{stem}.jpg"), draw_result(frame, result))
    return out_dir / f"{stem}.json"
