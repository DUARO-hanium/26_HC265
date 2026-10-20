#!/usr/bin/env python3
"""OMX-F 5축 팔 FK/IK (URDF 상수 기반, numpy 전용).

좌표계: link0(팔 베이스) 기준, 미터. x=앞, y=왼쪽, z=위.
IK는 "그리퍼가 수직 아래(phi=pi/2)를 향한 채 (x,y,z)에 TCP를 놓는" 해를 구함.

주의 (실기 검증 전):
  - 관절 축 방향/부호는 omx_f_arm.urdf.xacro 기준 가정 (j1=z, j2~j4=y, j5=x).
  - EE_OFFSET은 기본 OMX-F 그리퍼 기준. 커스텀 그리퍼면 `check`로 실측해서 고칠 것.
사용:
  python3 omx_ik.py ik 0.25 0.0 0.10
  python3 omx_ik.py fk 0 0.3 0.5 0.8 0
  python3 omx_ik.py selftest
  python3 omx_ik.py check <실측 x y z> <q1..q5>   # FK vs tf2_echo 비교
"""
import math
import sys
import numpy as np

J1_ORIGIN = np.array([-0.01125, 0.0, 0.034])
J2_ORIGIN = np.array([0.0, 0.0, 0.0635])
J3_ORIGIN = np.array([0.0415, 0.0, 0.11315])
J4_ORIGIN = np.array([0.162, 0.0, 0.0])
J5_ORIGIN = np.array([0.0287, 0.0, 0.0])
EE_OFFSET = np.array([0.09193, -0.0016, 0.0])  # 커스텀 그리퍼면 수정

SOFT_LIMIT = 2.5  # rad, 이보다 큰 관절각 해는 버림


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1.0, 0], [-s, 0, c]])


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])


def fk(q):
    """q=[q1..q5] -> (TCP 위치 3-vector, 회전행렬 3x3)."""
    q1, q2, q3, q4, q5 = q
    p = J1_ORIGIN.copy()
    R = _rz(q1)
    p = p + R @ J2_ORIGIN
    R = R @ _ry(q2)
    p = p + R @ J3_ORIGIN
    R = R @ _ry(q3)
    p = p + R @ J4_ORIGIN
    R = R @ _ry(q4)
    p = p + R @ J5_ORIGIN
    R = R @ _rx(q5)
    p = p + R @ EE_OFFSET
    return p, R


def ik_vertical(x, y, z, phi=math.pi / 2):
    """그리퍼 수직(phi=pi/2: 아래) IK. 성공 시 [q1..q5], 실패 시 None."""
    dx, dy = x - J1_ORIGIN[0], y - J1_ORIGIN[1]
    q1 = math.atan2(dy, dx)
    r = math.hypot(dx, dy)

    # 손끝 벡터(조인트5 + EE)를 평면 (r,z)로: phi 방향으로 길이 t_len
    t_len = J5_ORIGIN[0] + EE_OFFSET[0]
    wx = r - t_len * math.cos(phi)
    wz = z + t_len * math.sin(phi)  # phi=pi/2면 손목은 TCP보다 t_len 위

    sx, sz = 0.0, J1_ORIGIN[2] + J2_ORIGIN[2]
    d_x, d_z = wx - sx, wz - sz
    a = J3_ORIGIN[0]
    c = J3_ORIGIN[2]
    l1 = math.hypot(a, c)
    alpha = math.atan2(c, a)
    l2 = J4_ORIGIN[0]
    D2 = d_x * d_x + d_z * d_z
    cd = (D2 - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    if abs(cd) > 1.0:
        return None

    best = None
    for sgn in (+1, -1):
        delta = sgn * math.acos(cd)
        b1 = math.atan2(d_z, d_x) - math.atan2(l2 * math.sin(delta), l1 + l2 * math.cos(delta))
        b2 = b1 + delta
        q2 = alpha - b1
        q3 = -b2 - q2
        q4 = phi + b2
        qs = [q1, q2, q3, q4, 0.0]
        if any(abs(v) > SOFT_LIMIT for v in qs):
            continue
        elbow_z = sz + l1 * math.sin(b1)
        if best is None or elbow_z > best[0]:
            best = (elbow_z, qs)
    return None if best is None else best[1]


def _selftest():
    rng = np.random.default_rng(0)
    worst = 0.0
    n_ok = 0
    n_try = 0
    for _ in range(2000):
        x = rng.uniform(0.08, 0.30)
        y = rng.uniform(-0.15, 0.15)
        z = rng.uniform(0.02, 0.20)
        n_try += 1
        q = ik_vertical(x, y, z)
        if q is None:
            continue
        p, R = fk(q)
        err = np.linalg.norm(p - np.array([x, y, z]))
        # 툴 x축이 아래(-z)를 향하는지
        down = R[:, 0] @ np.array([0, 0, -1.0])
        # EE y 오프셋(-1.6mm)은 IK에서 무시 -> 수 mm 오차 허용
        worst = max(worst, err)
        assert err < 3e-3, (x, y, z, q, err)
        assert down > 0.999, (x, y, z, down)
        n_ok += 1
    print(f"selftest OK: {n_ok}/{n_try} 도달 가능, 최대 FK 오차 {worst*1000:.2f} mm")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "ik":
        x, y, z = map(float, sys.argv[2:5])
        q = ik_vertical(x, y, z)
        if q is None:
            print("도달 불가")
            sys.exit(1)
        p, _ = fk(q)
        print("q =", [round(v, 4) for v in q])
        print("FK 재계산 =", [round(float(v), 4) for v in p])
    elif cmd == "fk":
        q = list(map(float, sys.argv[2:7]))
        p, _ = fk(q)
        print("TCP =", [round(float(v), 4) for v in p])
    elif cmd == "selftest":
        _selftest()
    elif cmd == "check":
        meas = np.array(list(map(float, sys.argv[2:5])))
        q = list(map(float, sys.argv[5:10]))
        p, _ = fk(q)
        print("FK  =", np.round(p, 4))
        print("실측 =", np.round(meas, 4))
        print(f"차이 = {np.linalg.norm(p - meas)*1000:.1f} mm  (>10mm면 EE_OFFSET/그리퍼 확인)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
