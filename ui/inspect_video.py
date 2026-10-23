"""Run the DUARO defect-inspection MVP on a recorded video.

This is the camera-free entry point.  It uses the same detector as the live
dashboard and never fabricates detections when a model is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2

from live_inspection import (
    HeuristicStainDetector,
    TemporalDetectionGate,
    YoloDetector,
    configured_defect_classes,
)


def parse_args() -> argparse.Namespace:
    default_model = Path(__file__).resolve().parent.parent / "yolo26n.pt"
    parser = argparse.ArgumentParser(description="DUARO recorded-video inspection MVP")
    parser.add_argument("input", type=Path, help="Input video path")
    parser.add_argument(
        "--backend", choices=("heuristic", "yolo"), default="heuristic",
        help="Training-free OpenCV heuristic or a trained YOLO model",
    )
    parser.add_argument(
        "--model", default=str(default_model),
        help="YOLO .pt path; defaults to the repository's general yolo26n.pt demo weight",
    )
    parser.add_argument("--output", type=Path, help="Annotated MP4 output path")
    parser.add_argument("--confidence", type=float, default=0.50)
    parser.add_argument(
        "--classes", default="stain,discoloration,damage,tear,hole",
        help="Comma-separated defect class names; use * to accept every model class",
    )
    parser.add_argument("--infer-every", type=int, default=2)
    parser.add_argument("--tile-rows", type=int, default=2)
    parser.add_argument("--tile-columns", type=int, default=2)
    parser.add_argument("--tile-overlap", type=float, default=0.12)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    parser.add_argument("--full-frame-only", action="store_true")
    parser.add_argument("--heuristic-min-area", type=int, default=90)
    parser.add_argument("--heuristic-lab-red-min", type=int, default=135)
    parser.add_argument("--heuristic-min-saturation", type=int, default=35)
    parser.add_argument("--heuristic-min-score", type=float, default=0.40)
    parser.add_argument("--heuristic-max-candidates", type=int, default=1)
    parser.add_argument("--heuristic-min-red-excess", type=float, default=3.0)
    parser.add_argument("--heuristic-min-local-red-contrast", type=float, default=1.0)
    parser.add_argument("--heuristic-min-cloth-fraction", type=float, default=0.20)
    parser.add_argument("--heuristic-background-threshold", type=float, default=18.0)
    parser.add_argument("--heuristic-min-garment-area-ratio", type=float, default=0.03)
    parser.add_argument("--background-seconds", type=float, default=0.0)
    parser.add_argument("--confirm-frames", type=int, default=3)
    parser.add_argument("--release-frames", type=int, default=2)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, default=0.0)
    parser.add_argument(
        "--max-frames", type=int, default=0,
        help="Stop after N frames (0 processes the complete video)",
    )
    return parser.parse_args()


def inspect_video(args: argparse.Namespace) -> tuple[Path, Path, dict]:
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise RuntimeError(f"입력 영상을 찾을 수 없습니다: {input_path}")

    output_path = (args.output or input_path.with_name(f"{input_path.stem}_inspected.mp4"))
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path = output_path.with_suffix(".json")

    if args.backend == "heuristic":
        detector = HeuristicStainDetector(
            min_area=args.heuristic_min_area,
            lab_red_min=args.heuristic_lab_red_min,
            min_saturation=args.heuristic_min_saturation,
            min_score=args.heuristic_min_score,
            max_candidates=args.heuristic_max_candidates,
            min_red_excess=args.heuristic_min_red_excess,
            min_local_red_contrast=args.heuristic_min_local_red_contrast,
            min_cloth_fraction=args.heuristic_min_cloth_fraction,
            background_threshold=args.heuristic_background_threshold,
            min_garment_area_ratio=args.heuristic_min_garment_area_ratio,
        )
    else:
        detector = YoloDetector(
            args.model,
            args.confidence,
            configured_defect_classes(args.classes),
            tiled=not args.full_frame_only,
            tile_rows=args.tile_rows,
            tile_columns=args.tile_columns,
            tile_overlap=args.tile_overlap,
            nms_iou=args.nms_iou,
        )
    if not detector.ready:
        raise RuntimeError(detector.error or "결함 모델을 불러오지 못했습니다.")

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {input_path}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = 20.0
    if args.backend == "heuristic":
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, args.background_seconds) * 1000.0)
        ok, background = capture.read()
        if not ok:
            capture.release()
            raise RuntimeError("배경 등록용 프레임을 읽을 수 없습니다.")
        detector.set_background(background)
    if args.start_seconds > 0:
        capture.set(cv2.CAP_PROP_POS_MSEC, args.start_seconds * 1000.0)
    else:
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    writer = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"출력 영상을 만들 수 없습니다: {output_path}")

    frame_index = 0
    inferred_frames = 0
    frames_with_defects = 0
    highest_confidence: dict[str, float] = defaultdict(float)
    last_detections = []
    detection_gate = TemporalDetectionGate(
        args.confirm_frames if args.backend == "heuristic" else 1,
        args.release_frames,
    )
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
            if frame_index == 1 or frame_index % max(1, args.infer_every) == 0:
                raw_detections, _, _ = detector.predict(frame)
                last_detections = detection_gate.update(raw_detections)
                annotated = detector._draw(frame.copy(), last_detections)
                inferred_frames += 1
                if detector.error:
                    raise RuntimeError(detector.error)
                if last_detections:
                    frames_with_defects += 1
                for detection in last_detections:
                    highest_confidence[detection.label] = max(
                        highest_confidence[detection.label], detection.confidence
                    )
            else:
                annotated = detector._draw(frame.copy(), last_detections)
            writer.write(annotated)
            if frame_index % 100 == 0:
                print(f"처리 중: {frame_index} frames", flush=True)
            if args.max_frames > 0 and frame_index >= args.max_frames:
                break
            if args.end_seconds > 0:
                source_seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if source_seconds >= args.end_seconds:
                    break
    finally:
        capture.release()
        writer.release()

    if frame_index == 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("입력 영상에 읽을 수 있는 프레임이 없습니다.")

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "backend": args.backend,
        "detector": detector.display_name,
        "model": (
            str(Path(args.model).expanduser().resolve())
            if args.backend == "yolo" and args.model else None
        ),
        "verdict": "defect_suspected" if highest_confidence else "no_defect_detected",
        "note": (
            "검출 결과는 선택한 검출 방식과 촬영 조건의 검증 범위 안에서만 유효합니다. "
            "no_defect_detected는 무결함을 보증하지 않습니다."
        ),
        "frames": frame_index,
        "inferred_frames": inferred_frames,
        "frames_with_defects": frames_with_defects,
        "highest_confidence_by_class": dict(sorted(highest_confidence.items())),
        "settings": {
            "confidence": args.confidence,
            "classes": args.classes,
            "infer_every": max(1, args.infer_every),
            "tiled": not args.full_frame_only,
            "tile_rows": args.tile_rows,
            "tile_columns": args.tile_columns,
            "tile_overlap": args.tile_overlap,
            "nms_iou": args.nms_iou,
            "max_frames": args.max_frames,
            "heuristic_min_area": args.heuristic_min_area,
            "heuristic_lab_red_min": args.heuristic_lab_red_min,
            "heuristic_min_saturation": args.heuristic_min_saturation,
            "heuristic_min_score": args.heuristic_min_score,
            "heuristic_max_candidates": args.heuristic_max_candidates,
            "heuristic_min_red_excess": args.heuristic_min_red_excess,
            "heuristic_min_local_red_contrast": args.heuristic_min_local_red_contrast,
            "heuristic_min_cloth_fraction": args.heuristic_min_cloth_fraction,
            "heuristic_background_threshold": args.heuristic_background_threshold,
            "heuristic_min_garment_area_ratio": args.heuristic_min_garment_area_ratio,
            "background_seconds": args.background_seconds,
            "start_seconds": args.start_seconds,
            "end_seconds": args.end_seconds,
            "confirm_frames": args.confirm_frames,
            "release_frames": args.release_frames,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, report_path, report


def main() -> int:
    try:
        output_path, report_path, report = inspect_video(parse_args())
    except RuntimeError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"판정: {report['verdict']}")
    print(f"영상: {output_path}")
    print(f"리포트: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
