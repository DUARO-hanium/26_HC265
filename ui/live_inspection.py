"""Threaded camera capture and YOLO inference for the live dashboard."""

from __future__ import annotations

import os
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np


def parse_source(value: str) -> int | str | None:
    """OpenCV expects local camera indexes as ints and streams as strings."""
    value = value.strip()
    if not value:
        return None
    return int(value) if value.lstrip("-").isdigit() else value


def configured_defect_classes(value: str) -> set[str] | None:
    """Return None for all model classes, otherwise a normalized allow-list."""
    names = {part.strip().lower() for part in value.split(",") if part.strip()}
    return None if "*" in names else names


def normalized_roi(value: str) -> tuple[float, float, float, float]:
    """Parse a normalized x1,y1,x2,y2 inspection ROI."""
    try:
        coordinates = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise ValueError("HEURISTIC_ROI는 x1,y1,x2,y2 형식이어야 합니다.") from exc
    if len(coordinates) != 4:
        raise ValueError("HEURISTIC_ROI는 좌표 네 개가 필요합니다.")
    x1, y1, x2, y2 = coordinates
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError("HEURISTIC_ROI 좌표는 0~1 범위이며 x1<x2, y1<y2여야 합니다.")
    return x1, y1, x2, y2


class UdpFrameAssembler:
    """Reassemble versioned ESP32 JPEG chunks while accepting legacy JPEG datagrams."""

    MAGIC = b"DCAM"
    VERSION = 1
    HEADER = struct.Struct("!4sBBHHII")
    MAX_FRAME_SIZE = 2 * 1024 * 1024
    MAX_IN_FLIGHT = 4
    STALE_AFTER_SECONDS = 1.5

    def __init__(self):
        self._frames: dict[tuple[tuple[str, int], int], dict[str, Any]] = {}

    def push(self, packet: bytes, sender: tuple[str, int], now: float | None = None) -> bytes | None:
        if packet.startswith(b"\xff\xd8"):
            return packet
        if len(packet) < self.HEADER.size or packet[:4] != self.MAGIC:
            return None

        magic, version, header_size, chunk_index, chunk_count, frame_id, frame_size = self.HEADER.unpack_from(packet)
        if (magic != self.MAGIC or version != self.VERSION or header_size != self.HEADER.size
                or chunk_count == 0 or chunk_index >= chunk_count
                or frame_size == 0 or frame_size > self.MAX_FRAME_SIZE):
            return None

        timestamp = time.monotonic() if now is None else now
        self._discard_stale(timestamp)
        key = (sender, frame_id)
        frame = self._frames.get(key)
        if frame is None:
            frame = {"created": timestamp, "chunk_count": chunk_count,
                     "frame_size": frame_size, "chunks": {}}
            self._frames[key] = frame
        elif frame["chunk_count"] != chunk_count or frame["frame_size"] != frame_size:
            self._frames.pop(key, None)
            return None

        frame["chunks"][chunk_index] = packet[header_size:]
        if len(frame["chunks"]) != chunk_count:
            self._limit_in_flight()
            return None

        jpeg = b"".join(frame["chunks"][index] for index in range(chunk_count))
        self._frames.pop(key, None)
        if len(jpeg) != frame_size or not jpeg.startswith(b"\xff\xd8"):
            return None
        return jpeg

    def _discard_stale(self, now: float) -> None:
        stale = [key for key, frame in self._frames.items()
                 if now - frame["created"] > self.STALE_AFTER_SECONDS]
        for key in stale:
            self._frames.pop(key, None)

    def _limit_in_flight(self) -> None:
        while len(self._frames) > self.MAX_IN_FLIGHT:
            oldest = min(self._frames, key=lambda key: self._frames[key]["created"])
            self._frames.pop(oldest, None)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    xyxy: tuple[int, int, int, int]


@dataclass
class CameraSnapshot:
    name: str
    connected: bool = False
    jpeg: bytes | None = None
    detections: list[Detection] = field(default_factory=list)
    fps: float = 0.0
    latency_ms: float = 0.0
    captured_at: float = 0.0
    error: str | None = None
    model_ready: bool = False
    model_error: str | None = None
    simulated: bool = False


def inference_views(
    frame: np.ndarray,
    rows: int = 2,
    columns: int = 2,
    overlap: float = 0.12,
) -> list[tuple[np.ndarray, tuple[int, int]]]:
    """Return the full frame and overlapping crops with their source offsets.

    The full-frame pass preserves global context.  The crop passes make small
    defects occupy more input pixels, which is the useful part of the geometric
    crop idea for the first MVP.  Semantic collar/cuff/hem crops can replace the
    regular grid later without changing the detector interface.
    """
    height, width = frame.shape[:2]
    rows = max(1, int(rows))
    columns = max(1, int(columns))
    overlap = float(np.clip(overlap, 0.0, 0.45))
    views: list[tuple[np.ndarray, tuple[int, int]]] = [(frame, (0, 0))]
    if rows == 1 and columns == 1:
        return views

    tile_width = int(np.ceil(width / columns * (1.0 + overlap)))
    tile_height = int(np.ceil(height / rows * (1.0 + overlap)))
    for row in range(rows):
        center_y = (row + 0.5) * height / rows
        y1 = int(round(center_y - tile_height / 2))
        y1 = min(max(0, y1), max(0, height - tile_height))
        y2 = min(height, y1 + tile_height)
        for column in range(columns):
            center_x = (column + 0.5) * width / columns
            x1 = int(round(center_x - tile_width / 2))
            x1 = min(max(0, x1), max(0, width - tile_width))
            x2 = min(width, x1 + tile_width)
            views.append((frame[y1:y2, x1:x2], (x1, y1)))
    return views


def _intersection_over_union(first: Detection, second: Detection) -> float:
    ax1, ay1, ax2, ay2 = first.xyxy
    bx1, by1, bx2, by2 = second.xyxy
    intersection_width = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    first_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    second_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def suppress_duplicate_detections(
    detections: list[Detection], iou_threshold: float = 0.45
) -> list[Detection]:
    """Class-aware NMS for boxes repeated by full-frame and crop inference."""
    kept: list[Detection] = []
    for candidate in sorted(detections, key=lambda item: item.confidence, reverse=True):
        duplicate = any(
            candidate.label == selected.label
            and _intersection_over_union(candidate, selected) >= iou_threshold
            for selected in kept
        )
        if not duplicate:
            kept.append(candidate)
    return kept


class TemporalDetectionGate:
    """Confirm a candidate only after it persists at the same location."""

    def __init__(self, confirm_frames: int = 3, release_frames: int = 2,
                 match_iou: float = 0.20):
        self.confirm_frames = max(1, int(confirm_frames))
        self.release_frames = max(1, int(release_frames))
        self.match_iou = float(np.clip(match_iou, 0.0, 1.0))
        self.pending: Detection | None = None
        self.streak = 0
        self.misses = 0
        self.confirmed: list[Detection] = []

    def update(self, detections: list[Detection]) -> list[Detection]:
        if not detections:
            self.misses += 1
            if self.misses >= self.release_frames:
                self.pending = None
                self.streak = 0
                self.confirmed = []
            return list(self.confirmed)

        candidate = max(detections, key=lambda item: item.confidence)
        same_candidate = (
            self.pending is not None
            and candidate.label == self.pending.label
            and _intersection_over_union(candidate, self.pending) >= self.match_iou
        )
        self.streak = self.streak + 1 if same_candidate else 1
        self.pending = candidate
        self.misses = 0
        if self.streak >= self.confirm_frames:
            self.confirmed = [candidate]
        return list(self.confirmed)


def draw_detections(frame: np.ndarray, detections: list[Detection], score_name: str) -> np.ndarray:
    for detection in detections:
        x1, y1, x2, y2 = detection.xyxy
        cv2.rectangle(frame, (x1, y1), (x2, y2), (38, 74, 220), 2)
        text = f"{detection.label} {score_name} {detection.confidence:.2f}"
        cv2.putText(
            frame, text, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
            0.58, (38, 74, 220), 2, cv2.LINE_AA
        )
    return frame


class HeuristicStainDetector:
    """Training-free reddish-stain candidate detector for the current gray garment setup."""

    backend_name = "heuristic"
    display_name = "YOLO 기반"
    score_name = "score"
    warning = None

    def __init__(self, min_area: int = 90, max_area_ratio: float = 0.08,
                 lab_red_min: int = 135, min_saturation: int = 35,
                 roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.85),
                 min_score: float = 0.40, max_candidates: int = 1,
                 min_red_excess: float = 3.0,
                 min_local_red_contrast: float = 1.0,
                 min_cloth_fraction: float = 0.20,
                 background_threshold: float = 18.0,
                 min_garment_area_ratio: float = 0.03):
        self.min_area = max(1, int(min_area))
        self.max_area_ratio = float(np.clip(max_area_ratio, 0.001, 1.0))
        self.lab_red_min = int(np.clip(lab_red_min, 0, 255))
        self.min_saturation = int(np.clip(min_saturation, 0, 255))
        self.roi = roi
        self.min_score = float(np.clip(min_score, 0.0, 1.0))
        self.max_candidates = max(1, int(max_candidates))
        self.min_red_excess = max(0.0, float(min_red_excess))
        self.min_local_red_contrast = max(0.0, float(min_local_red_contrast))
        self.min_cloth_fraction = float(np.clip(min_cloth_fraction, 0.0, 1.0))
        self.background_threshold = max(1.0, float(background_threshold))
        self.min_garment_area_ratio = float(np.clip(min_garment_area_ratio, 0.001, 0.9))
        self._background: np.ndarray | None = None
        self._background_lock = threading.Lock()
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        return True

    @property
    def background_ready(self) -> bool:
        with self._background_lock:
            return self._background is not None

    def set_background(self, frame: np.ndarray) -> None:
        with self._background_lock:
            self._background = frame.copy()

    def garment_mask(self, frame: np.ndarray) -> np.ndarray:
        """Estimate the garment as the largest region changed from an empty scene."""
        with self._background_lock:
            background = None if self._background is None else self._background.copy()
        height, width = frame.shape[:2]
        empty = np.zeros((height, width), dtype=np.uint8)
        if background is None:
            return empty
        if background.shape[:2] != frame.shape[:2]:
            background = cv2.resize(background, (width, height), interpolation=cv2.INTER_AREA)

        current_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        background_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # Removing the global mean makes exposure changes less likely to turn
        # the complete frame into foreground.
        current_gray -= float(np.mean(current_gray))
        background_gray -= float(np.mean(background_gray))
        difference = np.abs(current_gray - background_gray)
        foreground = (difference >= self.background_threshold).astype(np.uint8) * 255
        foreground = cv2.morphologyEx(
            foreground, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)
        )
        foreground = cv2.morphologyEx(
            foreground, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8)
        )

        count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
        if count <= 1:
            return empty
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area < width * height * self.min_garment_area_ratio:
            return empty
        garment = (labels == component).astype(np.uint8) * 255
        return cv2.dilate(garment, np.ones((15, 15), np.uint8), iterations=1)

    def predict(self, frame: np.ndarray) -> tuple[list[Detection], np.ndarray, float]:
        started = time.perf_counter()
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        low_red = cv2.inRange(
            hsv, (0, self.min_saturation, 35), (18, 255, 255)
        )
        high_red = cv2.inRange(
            hsv, (165, self.min_saturation, 35), (179, 255, 255)
        )
        lab_a = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)[:, :, 1]
        subtle_red = cv2.inRange(lab_a, self.lab_red_min, 255)

        # High raw R alone also selects white and bright gray.  Require R to
        # dominate both G/B and the normalized RGB sum before accepting either
        # the HSV or the subtle Lab branch.
        blue, green, red = cv2.split(frame)
        blue_f = blue.astype(np.float32)
        green_f = green.astype(np.float32)
        red_f = red.astype(np.float32)
        red_excess = red_f - (green_f + blue_f) * 0.5
        red_ratio = red_f / (red_f + green_f + blue_f + 1.0)
        red_dominant = (
            (red_f >= 70.0)
            & (red_excess >= self.min_red_excess)
            & (red_ratio >= 0.355)
        ).astype(np.uint8) * 255
        hsv_red = cv2.bitwise_or(low_red, high_red)
        strong_red = cv2.bitwise_and(hsv_red, red_dominant)
        subtle_red = cv2.bitwise_and(subtle_red, red_dominant)
        mask = cv2.bitwise_or(strong_red, subtle_red)

        roi_mask = np.zeros((height, width), dtype=np.uint8)
        rx1 = int(round(self.roi[0] * width))
        ry1 = int(round(self.roi[1] * height))
        rx2 = int(round(self.roi[2] * width))
        ry2 = int(round(self.roi[3] * height))
        roi_mask[ry1:ry2, rx1:rx2] = 255
        mask = cv2.bitwise_and(mask, roi_mask)
        mask = cv2.bitwise_and(mask, self.garment_mask(frame))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        ranked_detections: list[tuple[float, Detection]] = []
        frame_area = max(1, width * height)
        for component in range(1, count):
            x, y, box_width, box_height, area = map(int, stats[component])
            if area < self.min_area or box_width < 7 or box_height < 7:
                continue
            if area > frame_area * self.max_area_ratio:
                continue

            component_pixels = labels[y:y + box_height, x:x + box_width] == component
            mean_redness = float(np.mean(lab_a[y:y + box_height, x:x + box_width][component_pixels]))
            mean_red_excess = float(np.mean(
                red_excess[y:y + box_height, x:x + box_width][component_pixels]
            ))

            # A stain must be redder than the nearby cloth, not merely reddish
            # in absolute terms.  Build a ring around the component and compare
            # against low-saturation, visible pixels that resemble gray cloth.
            margin_x = max(14, box_width)
            margin_y = max(14, box_height)
            sx1 = max(0, x - margin_x)
            sy1 = max(0, y - margin_y)
            sx2 = min(width, x + box_width + margin_x)
            sy2 = min(height, y + box_height + margin_y)
            surround_hsv = hsv[sy1:sy2, sx1:sx2]
            surround_a = lab_a[sy1:sy2, sx1:sx2]
            ring = np.ones(surround_a.shape, dtype=bool)
            ring[y - sy1:y - sy1 + box_height, x - sx1:x - sx1 + box_width] = False
            cloth_like = (
                ring
                & (surround_hsv[:, :, 1] < 105)
                & (surround_hsv[:, :, 2] > 45)
                & (surround_hsv[:, :, 2] < 235)
            )
            ring_count = max(1, int(np.count_nonzero(ring)))
            cloth_fraction = float(np.count_nonzero(cloth_like) / ring_count)
            if cloth_fraction < self.min_cloth_fraction or np.count_nonzero(cloth_like) < 30:
                continue
            local_redness = float(np.median(surround_a[cloth_like]))
            local_contrast = mean_redness - local_redness
            if local_contrast < self.min_local_red_contrast:
                continue

            redness = float(np.clip((mean_redness - 128.0) / 64.0, 0.0, 1.0))
            local_contrast_factor = float(np.clip(local_contrast / 16.0, 0.0, 1.0))
            red_excess_factor = float(np.clip(mean_red_excess / 48.0, 0.0, 1.0))
            fill_ratio = float(area / max(1, box_width * box_height))
            area_factor = float(np.clip(area / (frame_area * 0.01), 0.0, 1.0))
            score = float(np.clip(
                0.20 + 0.20 * redness + 0.20 * local_contrast_factor
                + 0.15 * red_excess_factor + 0.15 * fill_ratio
                + 0.10 * area_factor,
                0.0,
                0.95,
            ))
            if score < self.min_score:
                continue

            pad_x = max(8, int(round(box_width * 0.16)))
            pad_y = max(8, int(round(box_height * 0.12)))
            detection = Detection(
                "stain_candidate",
                score,
                (max(0, x - pad_x), max(0, y - pad_y),
                 min(width - 1, x + box_width + pad_x),
                 min(height - 1, y + box_height + pad_y)),
            )
            ranking = score * (0.5 + 0.5 * area_factor)
            ranked_detections.append((ranking, detection))

        ranked_detections.sort(key=lambda item: item[0], reverse=True)
        detections = [item[1] for item in ranked_detections[:self.max_candidates]]

        annotated = self._draw(frame.copy(), detections)
        return detections, annotated, (time.perf_counter() - started) * 1000

    def _draw(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        return draw_detections(frame, detections, self.score_name)


class YoloDetector:
    backend_name = "yolo"
    display_name = "YOLO + 분할 Crop"
    score_name = "conf"

    def __init__(self, model_path: str, confidence: float, defect_classes: set[str] | None,
                 tiled: bool = True, tile_rows: int = 2, tile_columns: int = 2,
                 tile_overlap: float = 0.12, nms_iou: float = 0.45):
        self.model_path = model_path
        self.confidence = confidence
        self.defect_classes = defect_classes
        self.tiled = tiled
        self.tile_rows = tile_rows
        self.tile_columns = tile_columns
        self.tile_overlap = tile_overlap
        self.nms_iou = nms_iou
        self.model: Any = None
        self.error: str | None = None
        self.warning: str | None = None
        self._lock = threading.Lock()
        self._load()

    @property
    def ready(self) -> bool:
        return self.model is not None

    def _load(self) -> None:
        if not self.model_path:
            self.error = "INSPECTION_MODEL_PATH가 설정되지 않았습니다."
            return
        path = Path(self.model_path).expanduser()
        if not path.is_file():
            self.error = f"모델 파일을 찾을 수 없습니다: {path}"
            return
        if path.name.lower() == "yolo26n.pt":
            self.warning = (
                "yolo26n.pt는 COCO 일반 객체 사전학습 모델입니다. 실행 구조 확인용이며 "
                "의류 오염을 학습한 모델이 아닙니다."
            )
        try:
            config_dir = Path(os.getenv("YOLO_CONFIG_DIR", Path(__file__).parent / ".ultralytics"))
            config_dir.mkdir(parents=True, exist_ok=True)
            os.environ["YOLO_CONFIG_DIR"] = str(config_dir)
            from ultralytics import YOLO

            self.model = YOLO(str(path))
        except Exception as exc:
            self.error = f"모델 로드 실패: {exc}"

    def predict(self, frame) -> tuple[list[Detection], Any, float]:
        if not self.ready:
            return [], frame, 0.0
        started = time.perf_counter()
        try:
            views = (inference_views(frame, self.tile_rows, self.tile_columns, self.tile_overlap)
                     if self.tiled else [(frame, (0, 0))])
            with self._lock:
                results = self.model.predict(
                    [view for view, _ in views], conf=self.confidence, verbose=False
                )
            detections: list[Detection] = []
            for result, (_, (offset_x, offset_y)) in zip(results, views):
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    label = str(result.names[class_id])
                    if self.defect_classes is not None and label.lower() not in self.defect_classes:
                        continue
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                    detections.append(Detection(
                        label,
                        float(box.conf.item()),
                        (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y),
                    ))
            detections = suppress_duplicate_detections(detections, self.nms_iou)
            annotated = self._draw(frame.copy(), detections)
            return detections, annotated, (time.perf_counter() - started) * 1000
        except Exception as exc:
            self.error = f"추론 실패: {exc}"
            return [], frame, (time.perf_counter() - started) * 1000

    @staticmethod
    def _draw(frame, detections: list[Detection]):
        return draw_detections(frame, detections, "conf")


class CameraWorker:
    def __init__(self, name: str, source: int | str | None, detector: YoloDetector,
                 infer_every: int = 2, simulated: bool = False, open_timeout_ms: int = 5000,
                 read_timeout_ms: int = 5000, width: int = 1280, height: int = 720,
                 requested_fps: int = 30, jpeg_quality: int = 75,
                 confirm_frames: int = 3, release_frames: int = 2):
        self.name = name
        self.source = source
        self.detector = detector
        self.infer_every = max(1, infer_every)
        self.simulated = simulated
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self.width = width
        self.height = height
        self.requested_fps = requested_fps
        self.jpeg_quality = int(np.clip(jpeg_quality, 40, 95))
        effective_confirm = confirm_frames if detector.backend_name == "heuristic" else 1
        self.detection_gate = TemporalDetectionGate(effective_confirm, release_frames)
        self._latest_raw_frame: np.ndarray | None = None
        self._background_samples: list[np.ndarray] = []
        self._snapshot = CameraSnapshot(name=name, simulated=simulated)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._inspection_active = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"camera-{name}", daemon=True)
        self._thread.start()

    def snapshot(self) -> CameraSnapshot:
        with self._lock:
            snap = self._snapshot
            return CameraSnapshot(name=snap.name, connected=snap.connected, jpeg=snap.jpeg,
                detections=list(snap.detections), fps=snap.fps, latency_ms=snap.latency_ms,
                captured_at=snap.captured_at, error=snap.error, model_ready=self.detector.ready,
                model_error=self.detector.error, simulated=snap.simulated)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def set_inspection_active(self, active: bool) -> None:
        """Keep the live feed running while gating inference and annotations."""
        active = bool(active)
        if self._inspection_active.is_set() == active:
            return
        self.detection_gate = TemporalDetectionGate(
            self.detection_gate.confirm_frames,
            self.detection_gate.release_frames,
            self.detection_gate.match_iou,
        )
        if active:
            self._inspection_active.set()
            return

        self._inspection_active.clear()
        with self._lock:
            frame = None if self._latest_raw_frame is None else self._latest_raw_frame.copy()
        if frame is not None:
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            self._publish(
                jpeg=encoded.tobytes() if ok else None,
                detections=[],
                latency_ms=0.0,
                captured_at=time.time(),
            )

    def calibrate_background(self) -> bool:
        with self._lock:
            frame = None if self._latest_raw_frame is None else self._latest_raw_frame.copy()
        if frame is None or self.detector.backend_name != "heuristic":
            return False
        self.detector.set_background(frame)
        self._background_samples.clear()
        self.detection_gate = TemporalDetectionGate(
            self.detection_gate.confirm_frames,
            self.detection_gate.release_frames,
            self.detection_gate.match_iou,
        )
        return True

    def _prepare_background(self, frame: np.ndarray) -> bool:
        """Collect ten startup frames before enabling heuristic detections."""
        with self._lock:
            self._latest_raw_frame = frame.copy()
        if self.detector.backend_name != "heuristic" or self.detector.background_ready:
            return True
        self._background_samples.append(frame.copy())
        if len(self._background_samples) >= 10:
            background = np.median(np.stack(self._background_samples), axis=0).astype(np.uint8)
            self.detector.set_background(background)
            self._background_samples.clear()
        return False

    def _publish(self, **values) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self._snapshot, key, value)

    def _open(self):
        capture = cv2.VideoCapture()
        capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms)
        capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms)
        capture.open(self.source)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.requested_fps)
        return capture

    def _run(self) -> None:
        if self.source is None:
            self._publish(connected=False, error="카메라 소스가 아직 설정되지 않았습니다.")
            return
        if isinstance(self.source, str) and self.source.lower().startswith("udp://"):
            self._run_udp()
            return
        capture = None
        frame_index = 0
        fps_frames = 0
        fps_started = time.perf_counter()
        measured_fps = 0.0
        last_detections: list[Detection] = []
        last_latency_ms = 0.0
        while not self._stop.is_set():
            frame_started = time.perf_counter()
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                capture = self._open()
                if not capture.isOpened():
                    self._publish(connected=False, error=f"카메라 소스를 열 수 없습니다: {self.source}")
                    self._stop.wait(2.0)
                    continue
            ok, frame = capture.read()
            if not ok:
                self._publish(connected=False, error="프레임 수신이 끊겼습니다. 재연결 중…")
                capture.release()
                capture = None
                self._stop.wait(0.5)
                continue
            frame_index += 1
            fps_frames += 1
            background_ready = self._prepare_background(frame)
            inspection_active = self._inspection_active.is_set()
            if inspection_active and background_ready and frame_index % self.infer_every == 0:
                raw_detections, _, last_latency_ms = self.detector.predict(frame)
                last_detections = self.detection_gate.update(raw_detections)
                annotated = self.detector._draw(frame.copy(), last_detections)
            elif not inspection_active:
                last_detections = []
                last_latency_ms = 0.0
                annotated = frame.copy()
            else:
                annotated = self.detector._draw(frame.copy(), last_detections)
            if self.simulated:
                cv2.rectangle(annotated, (12, 12), (245, 54), (15, 138, 230), -1)
                cv2.putText(annotated, "WI-FI CAMERA SIMULATION", (22, 41),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)
            elapsed = time.perf_counter() - fps_started
            if elapsed >= 1.0:
                measured_fps = fps_frames / elapsed
                fps_frames = 0
                fps_started = time.perf_counter()
            ok, encoded = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            self._publish(connected=True, jpeg=encoded.tobytes() if ok else None,
                detections=last_detections, fps=measured_fps, latency_ms=last_latency_ms,
                captured_at=time.time(), error=None)
            if self.simulated and self.requested_fps > 0:
                self._stop.wait(max(0.0, 1.0 / self.requested_fps - (time.perf_counter() - frame_started)))
        if capture is not None:
            capture.release()

    def _run_udp(self) -> None:
        """Receive the ESP32 firmware's one-JPEG-per-UDP-datagram protocol."""
        parsed = urlparse(str(self.source))
        host = parsed.hostname or "0.0.0.0"
        port = parsed.port or 8001
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        udp_socket.settimeout(1.0)
        try:
            udp_socket.bind((host, port))
        except OSError as exc:
            self._publish(connected=False, error=f"UDP {host}:{port} 포트를 열 수 없습니다: {exc}")
            udp_socket.close()
            return

        frame_index = 0
        fps_frames = 0
        fps_started = time.perf_counter()
        measured_fps = 0.0
        last_detections: list[Detection] = []
        last_latency_ms = 0.0
        assembler = UdpFrameAssembler()
        self._publish(connected=False, error=f"ESP32-CAM UDP 프레임 대기 중: {host}:{port}")
        while not self._stop.is_set():
            try:
                packet, sender = udp_socket.recvfrom(65535)
            except socket.timeout:
                self._publish(connected=False, error=f"ESP32-CAM 프레임 대기 중: UDP {port}")
                continue
            except OSError as exc:
                self._publish(connected=False, error=f"UDP 수신 오류: {exc}")
                break

            payload = assembler.push(packet, sender)
            if payload is None:
                continue
            frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                self._publish(connected=False, error="손상되거나 불완전한 JPEG 패킷을 받았습니다.")
                continue

            frame_index += 1
            fps_frames += 1
            background_ready = self._prepare_background(frame)
            inspection_active = self._inspection_active.is_set()
            if inspection_active and background_ready and frame_index % self.infer_every == 0:
                raw_detections, _, last_latency_ms = self.detector.predict(frame)
                last_detections = self.detection_gate.update(raw_detections)
                annotated = self.detector._draw(frame.copy(), last_detections)
            elif not inspection_active:
                last_detections = []
                last_latency_ms = 0.0
                annotated = frame.copy()
            else:
                annotated = self.detector._draw(frame.copy(), last_detections)
            elapsed = time.perf_counter() - fps_started
            if elapsed >= 1.0:
                measured_fps = fps_frames / elapsed
                fps_frames = 0
                fps_started = time.perf_counter()
            ok, encoded = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            self._publish(connected=True, jpeg=encoded.tobytes() if ok else None,
                          detections=last_detections, fps=measured_fps,
                          latency_ms=last_latency_ms, captured_at=time.time(), error=None)
        udp_socket.close()


class InspectionRuntime:
    def __init__(self, sources: dict[str, int | str | None], detector: Any, infer_every: int,
                 simulated_names: set[str] | None = None, open_timeout_ms: int = 5000,
                 read_timeout_ms: int = 5000, width: int = 1280, height: int = 720,
                 requested_fps: int = 30, jpeg_quality: int = 75,
                 confirm_frames: int = 3, release_frames: int = 2):
        self.detector = detector
        self.sources = sources
        simulated_names = simulated_names or set()
        self.workers = {
            name: CameraWorker(name, source, detector, infer_every, name in simulated_names,
                               open_timeout_ms, read_timeout_ms, width, height, requested_fps,
                               jpeg_quality, confirm_frames, release_frames)
            for name, source in sources.items()
        }

    @property
    def configured_names(self) -> list[str]:
        return [name for name, source in self.sources.items() if source is not None]

    def snapshot(self, name: str) -> CameraSnapshot:
        return self.workers[name].snapshot()

    def stop(self) -> None:
        for worker in self.workers.values():
            worker.stop()

    def calibrate_background(self, name: str) -> bool:
        return self.workers[name].calibrate_background()

    def set_inspection_active(self, active: bool) -> None:
        for worker in self.workers.values():
            worker.set_inspection_active(active)


def settings_from_env() -> dict[str, Any]:
    default_model = Path(__file__).resolve().parent.parent / "yolo26n.pt"
    return {
        "sources": {"1번 카메라": parse_source(os.getenv(
            "CAMERA_1_SOURCE", "udp://0.0.0.0:8001"))},
        "model_path": os.getenv("INSPECTION_MODEL_PATH", str(default_model)),
        "backend": os.getenv("INSPECTION_BACKEND", "heuristic").strip().lower(),
        "confidence": float(os.getenv("INSPECTION_CONFIDENCE", "0.5")),
        "defect_classes": configured_defect_classes(os.getenv(
            "INSPECTION_DEFECT_CLASSES", "stain,discoloration,damage,tear,hole")),
        "tiled": os.getenv("INSPECTION_TILED", "true").lower() in {"1", "true", "yes"},
        "tile_rows": int(os.getenv("INSPECTION_TILE_ROWS", "2")),
        "tile_columns": int(os.getenv("INSPECTION_TILE_COLUMNS", "2")),
        "tile_overlap": float(os.getenv("INSPECTION_TILE_OVERLAP", "0.12")),
        "nms_iou": float(os.getenv("INSPECTION_NMS_IOU", "0.45")),
        "heuristic_min_area": int(os.getenv("HEURISTIC_MIN_AREA", "90")),
        "heuristic_max_area_ratio": float(os.getenv("HEURISTIC_MAX_AREA_RATIO", "0.08")),
        "heuristic_lab_red_min": int(os.getenv("HEURISTIC_LAB_RED_MIN", "135")),
        "heuristic_min_saturation": int(os.getenv("HEURISTIC_MIN_SATURATION", "35")),
        "heuristic_roi": normalized_roi(os.getenv("HEURISTIC_ROI", "0,0,1,0.85")),
        "heuristic_min_score": float(os.getenv("HEURISTIC_MIN_SCORE", "0.40")),
        "heuristic_max_candidates": int(os.getenv("HEURISTIC_MAX_CANDIDATES", "1")),
        "heuristic_min_red_excess": float(os.getenv("HEURISTIC_MIN_RED_EXCESS", "3")),
        "heuristic_min_local_red_contrast": float(os.getenv(
            "HEURISTIC_MIN_LOCAL_RED_CONTRAST", "1")),
        "heuristic_min_cloth_fraction": float(os.getenv(
            "HEURISTIC_MIN_CLOTH_FRACTION", "0.20")),
        "heuristic_background_threshold": float(os.getenv(
            "HEURISTIC_BACKGROUND_THRESHOLD", "18")),
        "heuristic_min_garment_area_ratio": float(os.getenv(
            "HEURISTIC_MIN_GARMENT_AREA_RATIO", "0.03")),
        "infer_every": int(os.getenv("INSPECTION_INFER_EVERY", "2")),
        "simulated_names": {name for name, key in (("1번 카메라", "CAMERA_1_SIMULATION"),)
            if os.getenv(key, "false").lower() in {"1", "true", "yes"}},
        "open_timeout_ms": int(os.getenv("CAMERA_OPEN_TIMEOUT_MS", "5000")),
        "read_timeout_ms": int(os.getenv("CAMERA_READ_TIMEOUT_MS", "5000")),
        "width": int(os.getenv("CAMERA_WIDTH", "1280")),
        "height": int(os.getenv("CAMERA_HEIGHT", "720")),
        "requested_fps": int(os.getenv("CAMERA_FPS", "30")),
        "jpeg_quality": int(os.getenv("UI_JPEG_QUALITY", "75")),
        "confirm_frames": int(os.getenv("INSPECTION_CONFIRM_FRAMES", "3")),
        "release_frames": int(os.getenv("INSPECTION_RELEASE_FRAMES", "2")),
    }


def create_detector(settings: dict[str, Any]):
    """Build an interchangeable detector selected only by configuration."""
    if settings["backend"] == "heuristic":
        return HeuristicStainDetector(
            settings["heuristic_min_area"], settings["heuristic_max_area_ratio"],
            settings["heuristic_lab_red_min"], settings["heuristic_min_saturation"],
            settings["heuristic_roi"], settings["heuristic_min_score"],
            settings["heuristic_max_candidates"],
            settings["heuristic_min_red_excess"],
            settings["heuristic_min_local_red_contrast"],
            settings["heuristic_min_cloth_fraction"],
            settings["heuristic_background_threshold"],
            settings["heuristic_min_garment_area_ratio"],
        )
    if settings["backend"] == "yolo":
        return YoloDetector(
            settings["model_path"], settings["confidence"], settings["defect_classes"],
            settings["tiled"], settings["tile_rows"], settings["tile_columns"],
            settings["tile_overlap"], settings["nms_iou"],
        )
    raise ValueError("INSPECTION_BACKEND는 heuristic 또는 yolo여야 합니다.")
