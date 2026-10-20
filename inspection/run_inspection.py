"""
run_inspection.py — 한 면 또는 양면 검수 CLI

예)
  # 저장된 이미지로 Face A 한 장
  python -m inspection.run_inspection --weights weights/yolo_garment_defect.pt --image faceA.jpg --side A
  # ESP32-S3-CAM 실시간: Face A 촬영 → Enter → Face B 촬영 → 통합 판정
  python -m inspection.run_inspection --weights weights/yolo_garment_defect.pt --esp32 --both
"""
from __future__ import annotations

import argparse
import json

import cv2

from .inspector import YoloInspector, save_result
from .integrator import ResultIntegrator


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--conf", type=float, default=0.5, help="결함 확정 confidence 임계값")
    ap.add_argument("--uncertain-lo", type=float, default=0.35, help="이 값 이상 --conf 미만은 '판정 불확실'")
    ap.add_argument("--side", choices=["A", "B"], default="A")
    ap.add_argument("--image", help="저장된 영상 파일로 검수")
    ap.add_argument("--esp32", action="store_true", help="ESP32-S3-CAM UDP 수신으로 검수")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--both", action="store_true", help="Face A → Enter → Face B → 통합 판정")
    ap.add_argument("--out", default="outputs/inspection")
    args = ap.parse_args()

    integrator = ResultIntegrator(defect_conf_threshold=args.conf, uncertain_band=(args.uncertain_lo, args.conf))
    inspector = YoloInspector(args.weights, record_conf=integrator.record_conf)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            ap.error(f"이미지를 읽을 수 없음: {args.image}")
        res = inspector.inspect(frame, args.side)
        save_result(res, args.out, frame)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        return

    if not args.esp32:
        ap.error("--image 또는 --esp32 중 하나를 지정")

    from .esp32_frame_source import Esp32FrameSource

    src = Esp32FrameSource(port=args.port).start()
    try:
        sides = ["A", "B"] if args.both else [args.side]
        for side in sides:
            input(f"Face {side} 를 Inspection Camera 앞에 전개한 뒤 Enter...")
            frame = src.get_frame()
            res = inspector.inspect(frame, side)
            save_result(res, args.out, frame)
            integrator.add(res)
            found = "이상 없음" if res.passed else [d.cls_ko for d in res.defects]
            print(f"Face {side}: {found}  valid={res.valid}")
        if args.both:
            final = integrator.integrate()
            print(json.dumps(final.to_dict(), ensure_ascii=False, indent=2))
    finally:
        src.stop()


if __name__ == "__main__":
    main()
