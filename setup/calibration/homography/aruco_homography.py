"""ArUco 마커 4장으로 Homography H(픽셀→world 평면) 계산 후 JSON 저장

사전 준비 (README 참조):
  1. 마커 4장 인쇄 (DICT_4X4_50, ID 0~3, 한 변 5cm), 평면 모서리에 평평하게 부착
  2. 각 마커 "중심"의 로봇 베이스 기준 world 좌표 (x, y)를 실측해서
     marker_world.json 에 기록 (단위 m, 반드시 실측값):
       { "0": [<x>, <y>], "1": [<x>, <y>], "2": [<x>, <y>], "3": [<x>, <y>] }

사용법:
  # 카메라에서 바로 (기본 index 0)
  python aruco_homography.py --world marker_world_table.json --output H_table.json --z 0.0

  # 찍어둔 이미지 파일로
  python aruco_homography.py --world marker_world_bag.json --output H_bag.json --image bag.jpg --z 0.15

검증:
  python aruco_homography.py --world marker_world_table.json --check-only
  (재투영 오차 출력 — 픽셀 단위. 마커 4개 기준 수 픽셀 이내면 정상)
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ARUCO_DICT = cv2.aruco.DICT_4X4_50


def capture_frame(camera_index: int, width: int = 640, height: int = 480) -> np.ndarray:
    cap = cv2.VideoCapture(camera_index)
    # WSL2/usbip에서는 MJPG가 아니면 대역폭 초과로 실패 (lerobot 패치와 동일 이유)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        sys.exit(f"카메라 {camera_index} 열기 실패. usbipd attach / lerobot-find-cameras 확인")
    # 워밍업 몇 프레임 버리고 캡처 (자동노출 안정화)
    for _ in range(10):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit("프레임 캡처 실패")
    return frame


def detect_marker_centers(image: np.ndarray) -> dict[int, tuple[float, float]]:
    """마커 ID → 중심 픽셀 (u, v)"""
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT))
    corners, ids, _ = detector.detectMarkers(image)
    if ids is None:
        return {}
    centers = {}
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        c = marker_corners.reshape(4, 2).mean(axis=0)
        centers[int(marker_id)] = (float(c[0]), float(c[1]))
    return centers


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--world", required=True, help="마커 ID→world (x,y) 좌표 JSON 경로")
    p.add_argument("--output", default="H.json", help="저장할 H 행렬 JSON 경로")
    p.add_argument("--image", default=None, help="이미지 파일 사용 시 경로 (미지정 시 카메라 캡처)")
    p.add_argument("--camera", type=int, default=0, help="카메라 index (기본 0)")
    p.add_argument("--z", type=float, default=0.0, help="이 평면의 높이 (로봇 베이스 기준 m) — 메타데이터로 저장")
    p.add_argument("--check-only", action="store_true", help="H 저장 없이 검출·오차만 확인")
    p.add_argument("--save-annotated", default=None, help="검출 마커를 그린 이미지를 저장할 경로")
    p.add_argument("--intrinsics", default=None,
                   help="checkerboard_intrinsics.py가 만든 intrinsics.json 경로 — "
                        "지정 시 렌즈 왜곡을 편(undistort) 이미지 위에서 H를 만듦. "
                        "⚠️ 이 경우 런타임 비전도 같은 K·dist로 undistort한 이미지에서 픽셀을 뽑아야 함")
    args = p.parse_args()

    raw = json.loads(Path(args.world).read_text(encoding="utf-8"))
    world = {}
    for k, v in raw.items():
        if k.startswith("_"):  # "_comment" 등 메타 키 무시
            continue
        if (not isinstance(v, (list, tuple)) or len(v) != 2
                or not all(isinstance(c, (int, float)) for c in v)):
            sys.exit(f"{args.world}: 마커 {k}의 좌표가 실측값이 아님 ({v}) — "
                     f"null 자리에 로봇 베이스 기준 (x, y) 실측값(m)을 넣어야 함")
        world[int(k)] = [float(v[0]), float(v[1])]

    image = cv2.imread(args.image) if args.image else capture_frame(args.camera)
    if image is None:
        sys.exit(f"이미지 로드 실패: {args.image}")

    intr = None
    if args.intrinsics:
        intr = json.loads(Path(args.intrinsics).read_text(encoding="utf-8"))
        K = np.array(intr["K"], dtype=np.float64)
        dist = np.array(intr["dist"], dtype=np.float64)
        image = cv2.undistort(image, K, dist)
        print(f"왜곡 보정 적용: {args.intrinsics} (이후 검출·H는 보정된 이미지 기준)")

    centers = detect_marker_centers(image)
    print(f"검출된 마커: {sorted(centers)}")

    matched = sorted(set(centers) & set(world))
    if len(matched) < 4:
        sys.exit(f"대응점 부족: world 좌표가 있는 마커 {len(matched)}개 (최소 4개 필요). "
                 f"조명·가림·초점 확인 후 재시도")

    src = np.array([centers[i] for i in matched], dtype=np.float64)          # 픽셀 (u, v)
    dst = np.array([world[i] for i in matched], dtype=np.float64)            # world (x, y)

    H, _ = cv2.findHomography(src, dst, cv2.RANSAC)
    if H is None:
        sys.exit("findHomography 실패 — 마커가 일직선상이면 안 됨")

    # 재투영 오차: world→픽셀 역변환으로 픽셀 단위 오차 계산
    H_inv = np.linalg.inv(H)
    dst_h = np.hstack([dst, np.ones((len(dst), 1))])
    back = (H_inv @ dst_h.T).T
    back = back[:, :2] / back[:, 2:3]
    err = np.linalg.norm(back - src, axis=1)
    print(f"재투영 오차(픽셀): 평균 {err.mean():.2f} / 최대 {err.max():.2f}")
    if err.max() > 5.0:
        print("⚠️ 오차 큼 — 마커 부착 평면성·world 좌표 실측값 재확인 권장")

    if args.save_annotated:
        vis = image.copy()
        for i in matched:
            u, v = map(int, centers[i])
            cv2.circle(vis, (u, v), 6, (0, 0, 255), -1)
            cv2.putText(vis, f"id{i}", (u + 8, v - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite(args.save_annotated, vis)
        print(f"어노테이션 이미지 저장: {args.save_annotated}")

    if args.check_only:
        return

    out = {
        "H": H.tolist(),
        "plane_z": args.z,
        "marker_ids": matched,
        "marker_pixels": {str(i): centers[i] for i in matched},
        "marker_world": {str(i): world[i] for i in matched},
        "reprojection_error_px": {"mean": float(err.mean()), "max": float(err.max())},
        "image_size": [image.shape[1], image.shape[0]],
        # 왜곡 보정 여부 — true면 이 H를 쓰는 쪽(런타임 비전)도 같은 K·dist로
        # undistort한 이미지에서 픽셀을 뽑아야 함
        "undistorted": args.intrinsics is not None,
        "intrinsics_file": args.intrinsics,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {args.output}")


if __name__ == "__main__":
    main()
