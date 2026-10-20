#!/usr/bin/env python3
"""비전 결과(latest_result.json)가 새로 나오면 -> 팔별 호모그래피로 xyz 변환 -> go_down.py 호출.

기본은 dry-run(계산/출력만). 움직이려면 --execute (매번 Enter 확인), 완전 자동은 --execute --auto.

  # 계산만, 한 번 처리하고 종료
  python3 watch_and_go.py --json latest_result.json --calib-left calib_left.json --calib-right calib_right.json --once
  # 시연: 새 결과가 뜰 때마다 자동으로 두 팔 하강
  python3 watch_and_go.py --json latest_result.json --calib-left calib_left.json \
      --calib-right calib_right.json --execute --auto --overlay-out robot_target_px.json

--overlay-out : 로봇이 갈 위치를 다시 픽셀로 바꿔 JSON으로 저장 (대시보드가 비전 점과 겹쳐 그리는 용도)
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import homography_map as hm

HERE = Path(__file__).resolve().parent.parent  # go_down.py 는 한 칸 위 폴더


def target_uv(item):
    if "grasp_u" in item:
        if not item.get("grasp_found", True):
            raise ValueError(f"{item.get('arm')}: grasp_found=false")
        return float(item["grasp_u"]), float(item["grasp_v"])
    return float(item["u"]), float(item["v"])


def tips_gap(xyz, right_base):
    """오른팔 목표를 왼팔 link0 좌표로 옮겨 두 손끝 사이 거리(m)를 구한다. right_base=(x,y,z,yaw)"""
    import math
    bx, by, bz, yaw = right_base
    c, s = math.cos(yaw), math.sin(yaw)
    x, y, z = xyz["right"]
    p = (bx + c * x - s * y, by + s * x + c * y, bz + z)
    l = xyz["left"]
    return math.dist(p, l)


def process(result, calibs, thickness, margin_px, clearance, overlay_out, execute, auto, extra,
            right_base=None, min_gap=0.10):
    state = str(result.get("state"))
    targets = result.get("targets") or []
    if state in ("GRASP_PAIR_NOT_FOUND", "GRASP_PAIR_OUT_OF_REACH") or len(targets) not in (1, 2):
        print(f"[skip] state={state}, targets={len(targets)}")
        return False
    xyz, overlay, minz = {}, {}, {}
    for item in targets:
        arm = item["arm"]
        if arm not in calibs:
            print(f"[skip] {arm} 캘리브 파일 없음")
            return False
        u, v = target_uv(item)
        c = hm.load(calibs[arm])
        if not hm.in_hull(c, u, v, margin_px):
            print(f"[skip] {arm} 점 ({u:.0f},{v:.0f}) 가 기준점 영역 밖 -> 신뢰 낮음")
            return False
        x, y = hm.uv_to_xy(c, u, v)
        tz = c[2]
        xyz[arm] = [round(float(x), 4), round(float(y), 4), round(tz + thickness, 4)]
        minz[arm] = tz + clearance
        back = hm.xy_to_uv(c, x, y)
        overlay[arm] = {"u": round(float(back[0]), 1), "v": round(float(back[1]), 1)}
        print(f"[{arm}] 픽셀({u:.0f},{v:.0f}) -> xyz {xyz[arm]}  (책상 z={tz:.3f}, 최저 z={minz[arm]:.3f})")
    if overlay_out:
        Path(overlay_out).write_text(json.dumps(overlay))
    if len(xyz) == 1:   # 한 점 모드 (뒤집기: 한 팔, 한 점)
        arm = next(iter(xyz))
        cmd = [sys.executable, str(HERE / "go_down.py"), "--arm", arm, "--xyz", *map(str, xyz[arm]),
               "--min-z", str(minz[arm]), *extra]
        if execute:
            cmd.append("--execute")
            if auto:
                cmd.append("--yes")
        subprocess.run(cmd, check=False)
        return True
    if right_base is not None:
        gap = tips_gap(xyz, right_base)
        print(f"[두 손끝 간격] {gap*100:.1f} cm (최소 {min_gap*100:.0f} cm)")
        if gap < min_gap:
            print("[skip] 두 목표가 너무 가까움: 두 팔 충돌 위험")
            return False
    else:
        print("[주의] --right-base 미지정: 두 팔 간격 확인을 건너뜀")
    cmd = [sys.executable, str(HERE / "go_down.py"), "--both",
           "--left-xyz", *map(str, xyz["left"]), "--right-xyz", *map(str, xyz["right"]),
           "--min-z-left", str(minz["left"]), "--min-z-right", str(minz["right"]), *extra]
    if execute:
        cmd.append("--execute")
        if auto:
            cmd.append("--yes")
    subprocess.run(cmd, check=False)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--calib-left", required=True)
    ap.add_argument("--calib-right", required=True)
    ap.add_argument("--thickness", type=float, default=0.01, help="옷 두께 m (목표 z = 책상z + 이 값)")
    ap.add_argument("--clearance", type=float, default=0.003, help="책상 위 최저 여유 m")
    ap.add_argument("--margin-px", type=float, default=0.0, help="기준점 영역 밖 허용 픽셀")
    ap.add_argument("--overlay-out")
    ap.add_argument("--right-base", type=float, nargs=4, metavar=("X", "Y", "Z", "YAW"),
                    help="오른팔 베이스의 위치를 왼팔 link0 기준으로 (m, m, m, rad). 줄자로 실측")
    ap.add_argument("--min-gap", type=float, default=0.10, help="두 손끝 최소 간격 m")
    ap.add_argument("--poll", type=float, default=0.5)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--auto", action="store_true", help="Enter 확인 없이 실행")
    ap.add_argument("--go-down-arg", action="append", default=[], help="go_down.py 에 그대로 넘길 인자")
    a = ap.parse_args()
    calibs = {"left": a.calib_left, "right": a.calib_right}
    path = Path(a.json)
    last = None
    while True:
        if path.exists():
            m = path.stat().st_mtime
            if m != last:
                last = m
                try:
                    result = json.loads(path.read_text())
                    process(result, calibs, a.thickness, a.margin_px, a.clearance,
                            a.overlay_out, a.execute, a.auto, a.go_down_arg,
                            a.right_base, a.min_gap)
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    print("[error]", e)
                if a.once:
                    return
        elif a.once:
            raise SystemExit(f"{path} 없음")
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
