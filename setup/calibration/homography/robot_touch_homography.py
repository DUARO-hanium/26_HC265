"""로봇 EE 터치 방식으로 Homography H(픽셀→world 평면) 계산 후 JSON 저장.

ArUco 마커 없이, 로봇 그리퍼 끝(EE)이 평면 위 지점을 직접 터치한 위치를
대응점으로 사용한다. world 좌표는 FK에서 읽으므로 줄자 실측이 필요 없다.

절차 (README '참고 — 로봇 터치 방식' 섹션 참조):
  1. 로봇을 토크 오프(또는 teleop)로 움직여 평면 위 한 지점을 EE로 터치
  2. 이 스크립트 카메라 창에서 SPACE → 화면 정지 → 터치 지점을 마우스 클릭 (픽셀 취득)
  3. 터미널에 FK로 읽은 world 좌표 x y 입력 (ros2: tf2_echo world end_effector_link)
  4. 4점 이상 반복 (서로 멀리, 일직선 금지) → 'c' 키로 H 계산·저장

사용법:
  python robot_touch_homography.py --camera 0 --output H_table.json --z 0.0

키:
  SPACE = 현재 프레임 정지 후 클릭 대기 / r = 마지막 점 취소 / c = 계산·저장 / q = 중단
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def open_camera(camera_index: int, width: int = 640, height: int = 480) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(camera_index)
    # WSL2/usbip에서는 MJPG가 아니면 대역폭 초과로 실패 (lerobot 패치와 동일 이유)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        sys.exit(f"카메라 {camera_index} 열기 실패. usbipd attach / lerobot-find-cameras 확인")
    return cap


def ask_world_xy(point_no: int) -> tuple[float, float] | None:
    """터미널에서 world 좌표 입력받기. 빈 입력이면 취소(None)."""
    while True:
        raw = input(f"  점 {point_no}: FK world 좌표 'x y' 입력 (m, 예: 0.23 -0.11 / 빈 입력=이 점 취소): ").strip()
        if not raw:
            return None
        try:
            x, y = map(float, raw.replace(",", " ").split())
            return x, y
        except ValueError:
            print("  형식 오류 — 숫자 두 개를 공백으로 구분해 입력")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--camera", type=int, default=0, help="카메라 index (기본 0)")
    p.add_argument("--output", default="H.json", help="저장할 H 행렬 JSON 경로")
    p.add_argument("--z", type=float, default=0.0, help="이 평면의 높이 (로봇 베이스 기준 m) — 메타데이터로 저장")
    p.add_argument("--min-points", type=int, default=4, help="계산에 필요한 최소 대응점 수 (기본 4)")
    args = p.parse_args()

    cap = open_camera(args.camera)
    win = "robot_touch (SPACE=freeze&click, r=undo, c=compute, q=quit)"
    cv2.namedWindow(win)

    clicked: list[tuple[int, int]] = []  # 마우스 콜백이 채움

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked.append((x, y))

    cv2.setMouseCallback(win, on_mouse)

    pixels: list[tuple[float, float]] = []
    worlds: list[tuple[float, float]] = []
    frame = None

    print(__doc__)
    while True:
        ok, live = cap.read()
        if not ok:
            continue
        frame = live
        vis = live.copy()
        for i, (u, v) in enumerate(pixels):
            cv2.circle(vis, (int(u), int(v)), 6, (0, 0, 255), -1)
            cv2.putText(vis, f"P{i}", (int(u) + 8, int(v) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(vis, f"points: {len(pixels)}/{args.min_points}+", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow(win, vis)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            # 프레임 정지 → 클릭 대기 (로봇 EE가 터치 지점에 멈춰 있는 상태에서)
            clicked.clear()
            frozen = frame.copy()
            print(f"\n[점 {len(pixels)}] 화면 정지 — 터치 지점을 마우스로 클릭하세요 (ESC=취소)")
            while not clicked:
                cv2.imshow(win, frozen)
                if (cv2.waitKey(30) & 0xFF) == 27:  # ESC
                    break
            if not clicked:
                print("  클릭 취소")
                continue
            u, v = clicked[-1]
            marked = frozen.copy()
            cv2.circle(marked, (u, v), 6, (0, 0, 255), -1)
            cv2.imshow(win, marked)
            cv2.waitKey(1)
            xy = ask_world_xy(len(pixels))
            if xy is None:
                print("  이 점 취소")
                continue
            pixels.append((float(u), float(v)))
            worlds.append(xy)
            print(f"  저장: pixel({u}, {v}) <-> world({xy[0]}, {xy[1]})  [총 {len(pixels)}점]")

        elif key == ord("r") and pixels:
            pixels.pop(); worlds.pop()
            print(f"마지막 점 취소 — 남은 점 {len(pixels)}")

        elif key == ord("c"):
            if len(pixels) < args.min_points:
                print(f"대응점 부족: {len(pixels)}/{args.min_points}")
                continue
            break

        elif key == ord("q"):
            cap.release(); cv2.destroyAllWindows()
            sys.exit("중단됨 (저장 안 함)")

    cap.release()
    cv2.destroyAllWindows()

    src = np.array(pixels, dtype=np.float64)
    dst = np.array(worlds, dtype=np.float64)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC)
    if H is None:
        sys.exit("findHomography 실패 — 점들이 일직선상이면 안 됨")

    # 재투영 오차 (픽셀 단위)
    H_inv = np.linalg.inv(H)
    dst_h = np.hstack([dst, np.ones((len(dst), 1))])
    back = (H_inv @ dst_h.T).T
    back = back[:, :2] / back[:, 2:3]
    err = np.linalg.norm(back - src, axis=1)
    print(f"재투영 오차(픽셀): 평균 {err.mean():.2f} / 최대 {err.max():.2f}")
    if err.max() > 5.0:
        print("⚠️ 오차 큼 — 클릭 위치·FK 좌표 재확인 권장 ('r'로 재시작 불가, 재실행 필요)")

    out = {
        "H": H.tolist(),
        "plane_z": args.z,
        "method": "robot_touch",
        "points": [{"pixel": list(pxl), "world": list(w)} for pxl, w in zip(pixels, worlds)],
        "reprojection_error_px": {"mean": float(err.mean()), "max": float(err.max())},
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {args.output}")


if __name__ == "__main__":
    main()
