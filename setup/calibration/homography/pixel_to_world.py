"""픽셀 좌표 (u, v) → 로봇 world 좌표 (x, y) 변환

calibration/camera/aruco_homography.py 가 만든 H JSON을 로드해서 사용
비전(봉지 개구부 검출, CPN grasp point)이 준 픽셀 좌표를 로봇이 이동할 world 좌표로 바꾸는 유일한 통로 rule_based 모션은 전부 이 함수를 거침
 명령어 ↔ lerobot 소스 코드 매핑

사용 예 (CLI 검증):
    python -m common.pixel_to_world --h H_table.json --uv 320 240
"""

import argparse
import json
from pathlib import Path

import numpy as np


class PlaneTransform:

    def __init__(self, H: np.ndarray, plane_z: float = 0.0):
        self.H = np.asarray(H, dtype=np.float64)
        assert self.H.shape == (3, 3), f"H는 3x3이어야 함: {self.H.shape}"
        self.plane_z = float(plane_z)

    @classmethod
    def load(cls, h_json_path: str | Path) -> "PlaneTransform":
        data = json.loads(Path(h_json_path).read_text(encoding="utf-8"))
        return cls(np.array(data["H"]), data.get("plane_z", 0.0))

    def pixel_to_world(self, u: float, v: float) -> tuple[float, float]:
        p = self.H @ np.array([u, v, 1.0])
        return float(p[0] / p[2]), float(p[1] / p[2])

    def pixels_to_world(self, uv: np.ndarray) -> np.ndarray:
        uv = np.asarray(uv, dtype=np.float64)
        ones = np.ones((len(uv), 1))
        p = (self.H @ np.hstack([uv, ones]).T).T
        return p[:, :2] / p[:, 2:3]


def main():
    p = argparse.ArgumentParser(description="픽셀→world 변환 확인용 CLI")
    p.add_argument("--h", required=True, help="aruco_homography.py가 만든 H JSON 경로")
    p.add_argument("--uv", nargs=2, type=float, required=True, metavar=("U", "V"))
    args = p.parse_args()

    tf = PlaneTransform.load(args.h)
    x, y = tf.pixel_to_world(*args.uv)
    print(f"pixel ({args.uv[0]:.0f}, {args.uv[1]:.0f}) -> world ({x:.4f}, {y:.4f}) m, z={tf.plane_z}")


if __name__ == "__main__":
    main()
