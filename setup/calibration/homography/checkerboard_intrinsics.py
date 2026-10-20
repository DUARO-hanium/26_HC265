"""체커보드로 카메라 내부파라미터 K(3x3)·왜곡계수 dist 계산 → intrinsics.json 저장

체커보드 규격: "내부 코너" 개수 기준
ex) 10x7칸 보드 → 내부 코너 9x6 → --pattern 9x6

사용법:
  # 카메라로 라이브 캡처 (SPACE=캡처, q=종료 후 계산). 다양한 각도·거리로 15~30장
  python checkerboard_intrinsics.py --pattern 9x6 --square 0.025

  # 찍어둔 이미지 폴더 사용
  python checkerboard_intrinsics.py --pattern 9x6 --square 0.025 --images ./shots/*.jpg

참고: RMS 재투영 오차 0.5px 이하면 우수, 1.0px 이하면 사용 가능.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def collect_from_camera(camera_index: int, pattern: tuple[int, int]) -> list[np.ndarray]:
    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # WSL2/usbip 대역폭 대응
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        sys.exit(f"카메라 {camera_index} 열기 실패")

    frames = []
    print("SPACE=캡처 / q=종료. 체커보드를 다양한 각도·거리·위치로 15~30장 권장")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        found, _ = cv2.findChessboardCorners(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), pattern, None)
        vis = frame.copy()
        cv2.putText(vis, f"captured: {len(frames)}  board: {'OK' if found else '--'}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0) if found else (0, 0, 255), 2)
        cv2.imshow("checkerboard (SPACE=capture, q=quit)", vis)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and found:
            frames.append(frame.copy())
            print(f"캡처 {len(frames)}")
        elif key == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
    return frames


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pattern", default="9x6", help="내부 코너 수 WxH (기본 9x6)")
    p.add_argument("--square", type=float, required=True, help="정사각형 한 변 실측 길이 [m] (예: 0.025)")
    p.add_argument("--images", default=None, help="이미지 glob 패턴 (미지정 시 카메라 라이브 캡처)")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--output", default="intrinsics.json")
    args = p.parse_args()

    pw, ph = map(int, args.pattern.lower().split("x"))
    pattern = (pw, ph)

    if args.images:
        images = [cv2.imread(f) for f in sorted(glob.glob(args.images))]
        images = [im for im in images if im is not None]
    else:
        images = collect_from_camera(args.camera, pattern)

    if len(images) < 8:
        sys.exit(f"이미지 {len(images)}장 — 최소 8장, 권장 15장 이상")

    # 체커보드 3D 기준점 (z=0 평면)
    objp = np.zeros((pw * ph, 3), np.float32)
    objp[:, :2] = np.mgrid[0:pw, 0:ph].T.reshape(-1, 2) * args.square

    obj_points, img_points = [], []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    size = None
    for im in images:
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        found, corners = cv2.findChessboardCorners(gray, pattern, None)
        if not found:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        obj_points.append(objp)
        img_points.append(corners)

    print(f"코너 검출 성공: {len(obj_points)}/{len(images)}장")
    if len(obj_points) < 8:
        sys.exit("검출 성공 장수 부족 — 조명/초점/pattern 값 확인")

    rms, K, dist, _, _ = cv2.calibrateCamera(obj_points, img_points, size, None, None)
    print(f"RMS 재투영 오차: {rms:.3f}px  ({'우수' if rms < 0.5 else '사용 가능' if rms < 1.0 else '재촬영 권장'})")
    print(f"K =\n{K}")

    out = {
        "K": K.tolist(),
        "dist": dist.flatten().tolist(),
        "image_size": list(size),
        "rms_reprojection_error_px": float(rms),
        "pattern": args.pattern,
        "square_m": args.square,
        "num_images": len(obj_points),
    }
    Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"저장 완료: {args.output}")


if __name__ == "__main__":
    main()
