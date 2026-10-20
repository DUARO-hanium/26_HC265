#!/usr/bin/env python3
"""화면 픽셀 (u,v) <-> 팔 기준 책상 좌표 (x,y) 호모그래피.  팔마다 따로 만들어야함.

1) 기준점 CSV 만들기 (헤더 포함, 단위: u,v=픽셀 / x,y=미터, 팔 link0 기준)
       u,v,x,y
       412,300,0.180,0.060
       ...
   x,y 는 팔 끝(TCP)을 해당 표시에 대고 `tf2_echo world end_effector_link` 로 읽음.
2) 변환식 만들기:
       python3 homography_map.py fit --csv calib_left.csv --table-z -0.150 --out calib_left.json
   --table-z : 팔 끝을 책상에 살짝 대고 읽은 z (팔 link0 기준, m)
3) 쓰기:
       python3 homography_map.py map --calib calib_left.json 640 360     # 픽셀 -> x,y
       python3 homography_map.py inv --calib calib_left.json 0.22 0.05   # x,y -> 픽셀 (대시보드 겹치기용)
       python3 homography_map.py check --calib calib_left.json --csv test_points.csv   # 기준점 아닌 점으로 검증
       python3 homography_map.py selftest
주의: 카메라/해상도/책상 위치가 바뀌면 다시 만들어야함. 기준점 바깥으로는 부정확함.
"""
import argparse
import csv
import json
import sys

import numpy as np


def _apply(h, pts):
    pts = np.asarray(pts, float).reshape(-1, 2)
    ph = np.c_[pts, np.ones(len(pts))] @ np.asarray(h).T
    return ph[:, :2] / ph[:, 2:3]


def fit_h(uv, xy):
    import cv2
    h, _ = cv2.findHomography(np.asarray(uv, np.float64), np.asarray(xy, np.float64), 0)
    if h is None:
        raise SystemExit("호모그래피 계산 실패: 기준점이 한 줄에 몰려 있거나 부족함")
    return h


def read_csv(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append([float(r["u"]), float(r["v"]), float(r["x"]), float(r["y"])])
    a = np.array(rows)
    if len(a) < 4:
        raise SystemExit("기준점이 4개 미만")
    return a[:, :2], a[:, 2:]


def save(path, h, table_z, uv, xy):
    json.dump({"H": np.asarray(h).tolist(), "H_inv": np.linalg.inv(h).tolist(),
               "table_z": table_z, "uv": np.asarray(uv).tolist(), "xy": np.asarray(xy).tolist()},
              open(path, "w"), indent=2)


def load(path):
    d = json.load(open(path))
    return np.array(d["H"]), np.array(d["H_inv"]), float(d["table_z"]), np.array(d["uv"])


def uv_to_xy(calib, u, v):
    h, _, _, _ = load(calib) if isinstance(calib, str) else calib
    return _apply(h, [[u, v]])[0]


def xy_to_uv(calib, x, y):
    _, hi, _, _ = load(calib) if isinstance(calib, str) else calib
    return _apply(hi, [[x, y]])[0]


def in_hull(calib, u, v, margin_px=0.0):
    """(u,v) 가 기준점들이 만드는 볼록 영역 안인가 (바깥은 신뢰 낮음)."""
    import cv2
    _, _, _, uv = load(calib) if isinstance(calib, str) else calib
    hull = cv2.convexHull(uv.astype(np.float32))
    return cv2.pointPolygonTest(hull, (float(u), float(v)), True) >= -margin_px


def cmd_fit(a):
    uv, xy = read_csv(a.csv)
    h = fit_h(uv, xy)
    pred = _apply(h, uv)
    err = np.linalg.norm(pred - xy, axis=1) * 1000
    print(f"기준점 {len(uv)}개  재현 오차(mm): 평균 {err.mean():.1f} / 최대 {err.max():.1f}")
    for i, e in enumerate(err):
        print(f"  점{i}: {e:.1f} mm")
    # 안쪽 점 하나를 빼고 맞춰본 오차 = '모르는 점' 정확도 추정 (구석 점은 바깥 추정이 되므로 제외)
    import cv2
    hull_idx = set(int(i) for i in cv2.convexHull(uv.astype(np.float32), returnPoints=False).ravel())
    loo = []
    for i in range(len(uv)):
        if i in hull_idx:
            continue
        m = np.arange(len(uv)) != i
        try:
            hi = fit_h(uv[m], xy[m])
            loo.append(np.linalg.norm(_apply(hi, uv[i:i+1])[0] - xy[i]) * 1000)
        except SystemExit:
            pass
    if loo:
        print(f"  (안쪽 점 {len(loo)}개를 빼고 맞춰본 오차) 평균 {np.mean(loo):.1f} / 최대 {np.max(loo):.1f} mm  <- 실제 정확도에 가까움")
    else:
        print("  안쪽 기준점이 없어 정확도 추정 불가: 영역 중앙에 점을 1~2개 더 추가 권장")
    if err.max() > 20:
        print("경고: 최대 오차 20mm 초과. 기준점 재측정/추가 필요")
    save(a.out, h, a.table_z, uv, xy)
    print("저장:", a.out)


def cmd_check(a):
    uv, xy = read_csv(a.csv)
    c = load(a.calib)
    pred = _apply(c[0], uv)
    err = np.linalg.norm(pred - xy, axis=1) * 1000
    for i, e in enumerate(err):
        print(f"  검증점{i}: 오차 {e:.1f} mm")
    print(f"평균 {err.mean():.1f} / 최대 {err.max():.1f} mm")


def selftest():
    rng = np.random.default_rng(1)
    h_true = np.array([[3e-4, 1e-5, -0.10], [-2e-5, 4e-4, -0.12], [1e-6, 2e-6, 1.0]])
    uv = rng.uniform([200, 150], [1000, 600], (8, 2))
    xy = _apply(h_true, uv) + rng.normal(0, 0.001, (8, 2))  # 1mm 측정 잡음
    h = fit_h(uv, xy)
    test = rng.uniform([300, 200], [900, 550], (50, 2))
    err = np.linalg.norm(_apply(h, test) - _apply(h_true, test), axis=1) * 1000
    assert err.mean() < 3.0, err.mean()
    back = _apply(np.linalg.inv(h), _apply(h, test))
    assert np.abs(back - test).max() < 1e-6
    print(f"selftest OK: 1mm 잡음 기준점 8개 -> 영역 내 평균 오차 {err.mean():.2f} mm, 역변환 왕복 일치")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("fit"); f.add_argument("--csv", required=True); f.add_argument("--out", required=True)
    f.add_argument("--table-z", type=float, required=True)
    m = sp.add_parser("map"); m.add_argument("--calib", required=True); m.add_argument("u", type=float); m.add_argument("v", type=float)
    i = sp.add_parser("inv"); i.add_argument("--calib", required=True); i.add_argument("x", type=float); i.add_argument("y", type=float)
    c = sp.add_parser("check"); c.add_argument("--calib", required=True); c.add_argument("--csv", required=True)
    sp.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "fit":
        cmd_fit(a)
    elif a.cmd == "map":
        print([round(float(v), 4) for v in uv_to_xy(a.calib, a.u, a.v)])
    elif a.cmd == "inv":
        print([round(float(v), 1) for v in xy_to_uv(a.calib, a.x, a.y)])
    elif a.cmd == "check":
        cmd_check(a)
    else:
        selftest()


if __name__ == "__main__":
    main()
