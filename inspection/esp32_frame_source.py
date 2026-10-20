"""
esp32_frame_source.py — Inspection Camera(ESP32-S3-CAM) UDP 프레임 수신

setup/camera/esp32-cam 펌웨어는 JPEG 한 장을 UDP 패킷 하나로 보낸다 (기본 포트 8001).
setup/camera/esp32-cam/server/main.py 는 화면 표시 + mp4 저장용이고,
여기서는 검수 모듈이 "가장 최근 프레임 한 장" 을 가져오는 용도로만 최소 구현한다.
"""
from __future__ import annotations

import socket
import threading
import time

import cv2
import numpy as np


class Esp32FrameSource:
    def __init__(self, host: str = "0.0.0.0", port: int = 8001, buf_size: int = 65536):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self._sock.settimeout(0.5)
        self._buf_size = buf_size
        self._latest: np.ndarray | None = None
        self._latest_t = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "Esp32FrameSource":
        self._th.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._th.join(timeout=1.0)
        self._sock.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(self._buf_size)
            except socket.timeout:
                continue
            except OSError:
                break
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            with self._lock:
                self._latest, self._latest_t = frame, time.time()

    def get_frame(self, max_age_s: float = 1.0, timeout_s: float = 5.0) -> np.ndarray:
        """max_age_s 이내의 최신 프레임을 반환. 없으면 timeout_s 까지 기다린다."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            with self._lock:
                if self._latest is not None and time.time() - self._latest_t <= max_age_s:
                    return self._latest.copy()
            time.sleep(0.02)
        raise TimeoutError("Inspection Camera 프레임을 받지 못함 (ESP32-S3-CAM 연결/UDP 포트 확인)")
