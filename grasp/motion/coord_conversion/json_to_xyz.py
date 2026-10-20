#!/usr/bin/env python3
"""비전 JSON (u,v) -> 팔 기준 xyz -> go_down.py 인자.

입력 : garment_inspection_roi_mvp.py 가 저장하는 latest_result.json
        targets[i] = {arm: "left"|"right", grasp_u/grasp_v (GRASP) 또는 u/v (UNFOLD)}
보정 : uv_to_world 의 bundle (camera_intrinsics.yaml, eye_to_hand.yaml, environment_planes.yaml)
계산 : uv_to_world/runtime 과 같은 방식 (undistort -> 카메라 ray -> link0 -> 평면 교차)

예)
  python3 json_to_xyz.py latest_result.json --bundle ~/.ros/uv_to_world/calibrations/<profile>
  python3 json_to_xyz.py latest_result.json --bundle <profile> --run   # go_down.py --both 호출(dry-run)
  python3 json_to_xyz.py --selftest

주의
  * 비전은 /camera1/image_raw(왜곡 보정 전) 기준 (u,v) 이므로 여기서 undistort 해야함.
  * eye_to_hand 는 보정에 쓴 팔 하나의 link0 기준. 두 번째 팔은 --other-base 로
    "그 팔 link0 의 위치(첫 팔 link0 기준 x y z yaw)"를 실측해 넣어야 함.
  * 옷은 작업대 평면(worktop) 위로 가정. 옷 두께만큼 --z-offset 으로 올림.
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml


def quat_to_rot(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def load_bundle(bundle):
    b = Path(bundle).expanduser()
    intr = yaml.safe_load((b / "camera_intrinsics.yaml").read_text())
    k = np.array(intr["camera_matrix"]["data"], float).reshape(3, 3)
    d = np.array(intr["distortion_coefficients"]["data"], float)
    e = yaml.safe_load((b / "eye_to_hand.yaml").read_text())["calibration"]
    if not e.get("quality_passed", False):
        raise SystemExit("eye_to_hand.yaml: quality_passed 가 true 가 아님. 보정 먼저.")
    planes = yaml.safe_load((b / "environment_planes.yaml").read_text())
    p = planes["entrance_top_uv_to_point"]["ros__parameters"]  # worktop 평면
    if not p.get("calibration_valid", False):
        raise SystemExit("environment_planes.yaml: calibration_valid 가 true 가 아님.")
    return {
        "K": k, "D": d,
        "R": quat_to_rot(e["quaternion_xyzw"]),
        "t": np.array(e["translation"], float),
        "n": np.array(p["plane_normal"], float),
        "d": float(p["plane_offset"]),
    }


def uv_to_link0(cal, u, v):
    import cv2
    pt = np.array([[[u, v]]], np.float64)
    xn = cv2.undistortPoints(pt, cal["K"], cal["D"])[0, 0]  # 정규화 좌표
    ray_cam = np.array([xn[0], xn[1], 1.0])
    ray = cal["R"] @ ray_cam
    ray /= np.linalg.norm(ray)
    n = cal["n"] / np.linalg.norm(cal["n"])
    off = cal["d"] / np.linalg.norm(cal["n"])
    denom = float(n @ ray)
    if abs(denom) < 0.05:
        raise ValueError("ray 가 평면과 거의 평행")
    s = -(float(n @ cal["t"]) + off) / denom
    if s <= 0:
        raise ValueError("평면이 카메라 뒤쪽")
    return cal["t"] + s * ray


def to_other_arm(p, base):
    """첫 팔 link0 기준 점 p -> 다른 팔 link0 기준. base=(x,y,z,yaw_rad)"""
    bx, by, bz, yaw = base
    c, s = math.cos(yaw), math.sin(yaw)
    r = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    return r.T @ (p - np.array([bx, by, bz]))


def target_uv(item):
    if "grasp_u" in item:
        if not item.get("grasp_found", True):
            raise ValueError(f"{item.get('arm')}: grasp_found=false")
        return float(item["grasp_u"]), float(item["grasp_v"])
    return float(item["u"]), float(item["v"])


def convert(result, cal, ref_arm, other_base, z_offset):
    state = str(result.get("state"))
    if state in ("GRASP_PAIR_NOT_FOUND", "GRASP_PAIR_OUT_OF_REACH") or not result.get("targets"):
        raise SystemExit(f"비전 상태가 {state}: 좌표 사용 불가")
    if len(result["targets"]) != 2:
        raise SystemExit("targets 가 2개(left,right)가 아님")
    out = {}
    for item in result["targets"]:
        arm = item["arm"]
        u, v = target_uv(item)
        p = uv_to_link0(cal, u, v)
        if arm != ref_arm:
            if other_base is None:
                raise SystemExit(f"{arm} 팔 변환에는 --other-base x y z yaw 필요")
            p = to_other_arm(p, other_base)
        p = p + np.array([0, 0, z_offset])
        out[arm] = [round(float(x), 4) for x in p]
    return out


def selftest():
    """가상 카메라로 알려진 점을 투영 -> 역변환이 원래 점을 복원하는지."""
    import cv2
    K = np.array([[900, 0, 640], [0, 900, 360], [0, 0, 1.0]])
    D = np.array([-0.2, 0.05, 0, 0, 0.0])
    # 카메라가 link0 위 0.6m, 아래를 봄 (optical z = 월드 -z), optical x = 월드 +y
    R = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1.0]])
    R = R @ np.diag([1, 1, 1.0])
    t = np.array([0.25, 0.0, 0.6])
    cal = {"K": K, "D": D, "R": R, "t": t, "n": np.array([0, 0, 1.0]), "d": -0.0}
    worst = 0
    for w in ([0.22, 0.06, 0.0], [0.20, -0.07, 0.0], [0.28, 0.03, 0.0]):
        w = np.array(w)
        pc = R.T @ (w - t)
        uv, _ = cv2.projectPoints(pc.reshape(1, 1, 3), np.zeros(3), np.zeros(3), K, D)
        u, v = uv[0, 0]
        back = uv_to_link0(cal, u, v)
        worst = max(worst, float(np.linalg.norm(back - w)))
    assert worst < 1e-3, worst
    # 다른 팔 변환: 다른 팔이 x=0.0, y=+0.30 에 있고 yaw 0 이면 y 가 -0.30 이동
    q = to_other_arm(np.array([0.2, 0.1, 0.0]), (0.0, 0.30, 0.0, 0.0))
    assert np.allclose(q, [0.2, -0.2, 0.0])
    print(f"selftest OK: 왜곡 포함 투영 왕복 오차 {worst*1000:.4f} mm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="?")
    ap.add_argument("--bundle")
    ap.add_argument("--ref-arm", default="left", help="eye_to_hand 보정에 쓴 팔")
    ap.add_argument("--other-base", type=float, nargs=4, metavar=("X", "Y", "Z", "YAW"))
    ap.add_argument("--z-offset", type=float, default=0.01, help="옷 두께 등 (m)")
    ap.add_argument("--run", action="store_true", help="go_down.py --both 호출 (--execute 는 따로)")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.json and a.bundle):
        ap.error("json 과 --bundle 필요")
    result = json.loads(Path(a.json).read_text())
    cal = load_bundle(a.bundle)
    xyz = convert(result, cal, a.ref_arm, a.other_base, a.z_offset)
    print("팔 기준 xyz:", xyz)
    if a.run:
        if set(xyz) != {"left", "right"}:
            raise SystemExit("양쪽 팔 좌표가 모두 필요")
        cmd = [sys.executable, str(Path(__file__).resolve().parent.parent / "go_down.py"), "--both",
               "--left-xyz", *map(str, xyz["left"]), "--right-xyz", *map(str, xyz["right"])]
        if a.execute:
            cmd.append("--execute")
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
