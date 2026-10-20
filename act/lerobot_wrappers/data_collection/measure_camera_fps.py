#!/usr/bin/env python3
"""카메라 실측 fps 측정 — usbipd 경로 진단 + 카메라 브리지 스모크 테스트 겸용.

"1분 촬영 → 1초 영상" 증상은 실제 캡처 fps가 명목 30fps에 못 미칠 때 생긴다.
LeRobotDataset 의 timestamp 컬럼은 frame_index/fps 로 계산된 값이라 이 문제를
드러내지 못하므로, 녹화에 쓸 장치를 이 스크립트로 직접 실측한다.

사용 예 (conda activate lerobot 환경):
  python measure_camera_fps.py 0              # usbipd 카메라 진단 (기본 협상 포맷)
  python measure_camera_fps.py 0 --mjpg       # MJPG 강제 시 차이 비교 → 원인 분리
  python measure_camera_fps.py 10             # 브리지(/dev/video10) 스모크 테스트

판정: 29.0 ≤ 실측 fps ≤ 31.0 → PASS (zenoh 데이터 계약의 카메라 주기 기준)
"""

import argparse
import sys
import time

import cv2


def fourcc_to_str(v: float) -> str:
    v = int(v)
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("camera", help="카메라 index(예: 0) 또는 장치 경로(예: /dev/video10)")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30, help="요청/기대 fps")
    p.add_argument("--seconds", type=float, default=10.0, help="측정 시간")
    p.add_argument("--mjpg", action="store_true", help="FOURCC를 MJPG로 강제 (YUYV 협상 문제 분리용)")
    args = p.parse_args()

    source = int(args.camera) if args.camera.isdigit() else args.camera
    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"FAIL: 카메라를 열 수 없음: {args.camera}", file=sys.stderr)
        return 1

    # MJPG 강제는 해상도 설정보다 먼저 해야 적용된다 (OpenCV 협상 순서 특성)
    if args.mjpg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)

    actual_fourcc = fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC))
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"협상 결과: {actual_w}x{actual_h} FOURCC={actual_fourcc} "
          f"(요청: {args.width}x{args.height}@{args.fps}"
          f"{' MJPG' if args.mjpg else ''})")

    # 워밍업: 자동 노출 안정화 + 첫 프레임 지연 배제
    warmup_end = time.perf_counter() + 1.0
    while time.perf_counter() < warmup_end:
        cap.read()

    frames = 0
    slow_frames = 0  # 기대 주기의 2배를 넘긴 프레임 간격
    t0 = time.perf_counter()
    last = t0
    max_gap = 0.0
    while (now := time.perf_counter()) - t0 < args.seconds:
        ok, _ = cap.read()
        if not ok:
            print("FAIL: 프레임 읽기 실패 (스트림 끊김)", file=sys.stderr)
            cap.release()
            return 1
        gap = now - last
        last = now
        if frames > 0:
            max_gap = max(max_gap, gap)
            if gap > 2.0 / args.fps:
                slow_frames += 1
        frames += 1
    elapsed = time.perf_counter() - t0
    cap.release()

    measured = frames / elapsed
    print(f"실측: {frames} frames / {elapsed:.1f}s = {measured:.2f} fps")
    print(f"최대 프레임 간격: {max_gap * 1000:.0f} ms, "
          f"느린 프레임(>{2000 / args.fps:.0f}ms): {slow_frames}개")

    if 29.0 <= measured <= args.fps + 1.0:
        print("판정: PASS — 녹화에 사용 가능")
        return 0
    print(f"판정: FAIL — 실측 {measured:.2f} fps 는 기준(29~{args.fps + 1}) 미달. "
          "이 장치로 녹화하면 영상·관절값이 언더샘플링된다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
