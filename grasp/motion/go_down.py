#!/usr/bin/env python3
"""3D 좌표(팔 베이스 기준, m)를 받아 OMX-F가 그 위로 이동 -> 수직 하강 (-> 잡기 -> 들기 -> 놓기).

기본은 dry-run(계산만 출력). 실제로 움직이려면 --execute.

좌표를 주는 방법 2가지
  A) 터미널에서 직접:   --xyz X Y Z
  B) 자동 수신(ROS 토픽): --listen /target_point    (geometry_msgs/PointStamped, x y z = 팔 link0 기준 m)
     다른 노드(팀원의 좌표 변환 코드)가 그 토픽에 publish 하면 이 프로그램이 받아서 즉시 내려간다.
     테스트: ros2 topic pub --once /target_point geometry_msgs/msg/PointStamped \
             "{header: {frame_id: link0}, point: {x: 0.22, y: 0.03, z: 0.04}}"

예)
  python3 go_down.py --arm single --xyz 0.22 0.03 0.04                    # 계산만
  python3 go_down.py --arm single --xyz 0.22 0.03 0.04 --execute          # 한 팔 (/arm_controller/...)
  python3 go_down.py --both --left-xyz 0.22 0.05 0.04 --right-xyz 0.22 -0.05 0.04 --execute
  python3 go_down.py --arm single --listen /target_point --execute        # 좌표 자동 수신

잡기/들기 (그리퍼 값은 기본값이 없다. /joint_states 로 실측해서 넣는다. 순서는 README 참고)
  --grip --grip-open <rad> --grip-close <rad>   # gripper_joint_1 값. 두 값 사이로만 명령한다(클램프)
  --grip-mode auto|action|traj                  # action: omx_f.launch (GripperCommand 액션)
                                                # traj:   omx_f_follower_ai.launch (arm_controller 6번째 관절)
  --grip-current <mA>                           # 닫기 전 그리퍼 모터 Goal Current 제한 (기본 200)
  --lift-dz 0.10                                # 잡은 뒤 이만큼(m) 수직으로 들어올림 (0이면 안 듦)
  --release                                     # 들어올린 뒤 그리퍼를 다시 연다

좌표는 "각 팔 자신의 link0 기준"이다. 두 팔이 공통 월드 프레임이면 호출 전에 변환할 것.
"""
import argparse
import math
import sys
import time

from omx_ik import ik_vertical

PRE_GRASP_DZ = 0.06   # 목표 위 이 높이에서 먼저 정지
MAX_CORR = 0.15       # --correct 가 더할 수 있는 관절당 최대 보정(rad, 약 8.6도)
MIN_Z = 0.03          # TCP 최저 높이 하한 기본값. 팔 베이스가 책상보다 높이 있으면
                      # z가 음수일 수 있으므로 --min-z-left/right 로 책상z+여유를 넘길 것
MAX_REACH_XY = 0.32   # 대략적인 수평 도달 한계 (베이스 기준)
JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5"]
GRIP_CURRENT_MAX = 600   # --grip-current 상한(mA). ROBOTIS xacro 기본값. 이보다 크게는 쓰지 않는다


def plan(xyz, pre_dz, min_z=MIN_Z, lift_dz=0.0):
    x, y, z = xyz
    if z < min_z:
        raise SystemExit(f"z={z:.3f} < min_z({min_z}): 너무 낮음 (책상 z+여유보다 아래)")
    if (x * x + y * y) ** 0.5 > MAX_REACH_XY:
        raise SystemExit("수평 거리가 너무 멂")
    pre = ik_vertical(x, y, z + pre_dz)
    low = ik_vertical(x, y, z)
    up = ik_vertical(x, y, z + lift_dz) if lift_dz > 0 else None
    if pre is None or low is None or (lift_dz > 0 and up is None):
        raise SystemExit(f"도달 불가: {xyz}")
    return pre, low, up


def with_ns(ns, name):
    """name 앞에 네임스페이스를 붙인다. name 은 '/' 없이 시작."""
    return f"/{ns}/{name}" if ns else f"/{name}"


def topic_for(a, ns):
    if a.traj_topic:
        return a.traj_topic
    return with_ns(ns, "arm_controller/joint_trajectory")


def gripper_action_for(a, ns):
    if a.gripper_action:
        return a.gripper_action
    return with_ns(ns, "gripper_controller/gripper_cmd")


def dxl_srv_for(a, ns):
    if a.dxl_set_srv:
        return a.dxl_set_srv
    return with_ns(ns, "dynamixel_hardware_interface/set_dxl_data")


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["left", "right", "single"], default="single")
    ap.add_argument("--xyz", type=float, nargs=3)
    ap.add_argument("--listen", metavar="TOPIC", help="PointStamped 토픽에서 좌표를 자동 수신 (한 팔 모드, --arm 필요)")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--left-xyz", type=float, nargs=3)
    ap.add_argument("--right-xyz", type=float, nargs=3)
    ap.add_argument("--ns-left", default="left")
    ap.add_argument("--ns-right", default="right")
    ap.add_argument("--joint-prefix", default="", help="조인트 이름 접두어 (예: left_)")
    ap.add_argument("--traj-topic", help="팔 궤적 토픽 직접 지정. 기본 /<ns>/arm_controller/joint_trajectory "
                                         "(omx_f_follower_ai.launch 는 /leader/joint_trajectory 로 리맵됨)")
    ap.add_argument("--t-pre", type=float, default=4.0, help="현재->사전위치 시간(s)")
    ap.add_argument("--t-down", type=float, default=3.0, help="사전위치->하강 시간(s)")
    ap.add_argument("--t-grip", type=float, default=1.5, help="그리퍼 여닫는 시간(s)")
    ap.add_argument("--t-lift", type=float, default=3.0, help="들어올리는 시간(s)")
    ap.add_argument("--pre-dz", type=float, default=PRE_GRASP_DZ)
    ap.add_argument("--lift-dz", type=float, default=0.0, help="잡은 뒤 들어올릴 높이(m). 0이면 안 듦")
    ap.add_argument("--min-z-left", type=float, default=MIN_Z)
    ap.add_argument("--min-z-right", type=float, default=MIN_Z)
    ap.add_argument("--min-z", type=float, default=None, help="단일 팔 최저 z")
    # 그리퍼
    ap.add_argument("--grip", action="store_true", help="하강 후 그리퍼를 닫는다 (--grip-open/--grip-close 필수)")
    ap.add_argument("--grip-mode", choices=["auto", "action", "traj"], default="auto",
                    help="action: GripperCommand 액션(omx_f.launch), traj: arm_controller 궤적의 6번째 관절(omx_f_follower_ai.launch). "
                         "auto: 액션 서버가 있으면 action, 없으면 traj")
    ap.add_argument("--gripper-action", help="그리퍼 액션 이름. 기본: /<ns>/gripper_controller/gripper_cmd")
    ap.add_argument("--gripper-joint", default="gripper_joint_1", help="그리퍼 관절 이름 (joint-prefix 가 앞에 붙음)")
    ap.add_argument("--grip-open", type=float, help="열림 위치 (gripper_joint_1 값 rad, /joint_states 로 실측)")
    ap.add_argument("--grip-close", type=float, help="닫힘 위치 (gripper_joint_1 값 rad, /joint_states 로 실측)")
    ap.add_argument("--grip-limit", type=float, nargs=2, metavar=("LO", "HI"),
                    help="그리퍼 명령 허용 범위(rad). 생략하면 open/close 두 값 사이로 제한")
    ap.add_argument("--grip-current", type=int, default=200,
                    help=f"닫기 전 그리퍼 모터 Goal Current(mA, 0이면 안 씀, 최대 {GRIP_CURRENT_MAX}). "
                         "모터가 Current-based Position 모드(5)일 때만 힘 제한으로 작동")
    ap.add_argument("--grip-id", type=int, default=16, help="그리퍼 Dynamixel ID")
    ap.add_argument("--dxl-set-srv", help="Goal Current 를 쓰는 서비스 이름. 기본 /<ns>/dynamixel_hardware_interface/set_dxl_data")
    ap.add_argument("--grip-empty-tol", type=float, default=0.05,
                    help="닫은 뒤 실제 위치가 close 값과 이 이내(rad)면 '빈손'으로 판정하고 들지 않음")
    ap.add_argument("--lift-anyway", action="store_true", help="빈손 판정이어도 들어올린다")
    ap.add_argument("--release", action="store_true", help="들어올린 뒤 그리퍼를 연다")
    ap.add_argument("--grip-effort", type=float, default=0.0, help="GripperCommand max_effort (position_controllers 에서는 무시됨)")
    ap.add_argument("--correct", type=int, default=0, metavar="N",
                    help="하강 후 /joint_states 로 실제 관절각을 읽어 명령과의 차이만큼 보정해 다시 보낸다(N회, 처짐 보상). 0이면 끔")
    ap.add_argument("--yes", action="store_true", help="Enter 확인 생략 (자동 시연용)")
    ap.add_argument("--execute", action="store_true")
    return ap


def grip_bounds(a):
    """그리퍼 명령을 가둘 (lo, hi). --grip-limit 이 있으면 그것과 open/close 범위의 교집합."""
    lo, hi = min(a.grip_open, a.grip_close), max(a.grip_open, a.grip_close)
    if a.grip_limit:
        l2, h2 = min(a.grip_limit), max(a.grip_limit)
        lo, hi = max(lo, l2), min(hi, h2)
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo >= hi:
        raise SystemExit(f"그리퍼 허용 범위가 비어 있음: open/close {a.grip_open}/{a.grip_close}, limit {a.grip_limit}")
    return lo, hi


def grip_clamp(a, pos):
    lo, hi = grip_bounds(a)
    return min(max(float(pos), lo), hi)


def make_plans(a, jobs):
    plans = []
    for label, ns, xyz in jobs:
        mz = {"left": a.min_z_left, "right": a.min_z_right}.get(label, MIN_Z)
        if a.min_z is not None:
            mz = a.min_z
        pre, low, up = plan(xyz, a.pre_dz, mz, a.lift_dz)
        plans.append((label, ns, pre, low, up))
        print(f"[{label}] 목표 {xyz} -> topic {topic_for(a, ns)}")
        print(f"   사전위치 q = {[round(v, 3) for v in pre]}")
        print(f"   하강위치 q = {[round(v, 3) for v in low]}")
        if up:
            print(f"   들기위치 q = {[round(v, 3) for v in up]}  (+{a.lift_dz*100:.0f} cm)")
        if a.grip:
            lo, hi = grip_bounds(a)
            print(f"   그리퍼: 열림 {grip_clamp(a, a.grip_open):.3f} -> 닫힘 {grip_clamp(a, a.grip_close):.3f} (허용 {lo:.3f}~{hi:.3f}), "
                  f"Goal Current {a.grip_current if a.grip_current > 0 else '제한 안 함'} mA, 빈손 판정 폭 {a.grip_empty_tol} rad"
                  + (", 들고 나서 놓음" if a.release else ""))
    return plans


class Gripper:
    """런치 종류에 따라 액션 또는 궤적으로 그리퍼를 보내고, /joint_states 로 실제 위치를 읽는다."""

    def __init__(self, a, node, ns, pub, joint_name):
        self.a, self.node, self.ns, self.pub, self.joint = a, node, ns, pub, joint_name
        self.mode = None
        self.client = None
        self.srv = None

    def _tag(self):
        return self.ns or "single"

    def _call(self, client, req, timeout=2.0):
        import rclpy
        fut = client.call_async(req)
        end = time.time() + timeout
        while time.time() < end and not fut.done():
            rclpy.spin_once(self.node, timeout_sec=0.05)
        return fut.result() if fut.done() else None

    def setup(self):
        """전송 방식 결정 + (요청 시) Goal Current 제한을 먼저 확정. 실패하면 SystemExit (그리퍼를 움직이기 전)."""
        from rclpy.action import ActionClient
        from control_msgs.action import GripperCommand
        a = self.a
        if a.grip_mode in ("auto", "action"):
            name = gripper_action_for(a, self.ns)
            c = ActionClient(self.node, GripperCommand, name)
            if c.wait_for_server(timeout_sec=3.0):
                self.mode, self.client = "action", c
            elif a.grip_mode == "action":
                raise SystemExit(f"그리퍼 액션 서버 없음: {name} (ros2 action list 로 확인)")
        if self.mode is None:
            self.mode = "traj"
        self.node.get_logger().info(f"[{self._tag()}] 그리퍼 전송 방식: {self.mode}")
        if a.grip_current <= 0:
            self.node.get_logger().warn(f"[{self._tag()}] --grip-current 0: 힘 제한 없이 닫는다 (xacro 의 Goal Current 그대로)")
            return
        from dynamixel_interfaces.srv import SetDataToDxl, GetDataFromDxl
        set_name = dxl_srv_for(a, self.ns)
        get_name = set_name.replace("set_dxl_data", "get_dxl_data")
        self.srv = self.node.create_client(SetDataToDxl, set_name)
        getter = self.node.create_client(GetDataFromDxl, get_name)
        if not self.srv.wait_for_service(timeout_sec=3.0):
            raise SystemExit(f"{set_name} 서비스 없음: 힘 제한을 걸 수 없음. 하드웨어 인터페이스 확인, 또는 --grip-current 0 으로 명시적으로 끌 것")
        # 모터가 Current-based Position(5) 모드인지 확인. 아니면 Goal Current 가 힘 제한으로 작동하지 않는다.
        if getter.wait_for_service(timeout_sec=3.0):
            req = GetDataFromDxl.Request()
            req.id = int(a.grip_id)
            req.item_name = "Operating Mode"
            req.timeout_sec = 1.0
            res = self._call(getter, req, 3.0)
            if res is None or not res.result:
                raise SystemExit(f"ID {a.grip_id} Operating Mode 읽기 실패 ({get_name})")
            if res.item_data != 5:
                raise SystemExit(f"ID {a.grip_id} Operating Mode = {res.item_data} (5 가 아님): Goal Current 가 힘 제한이 되지 않는다. "
                                 "xacro 의 dxl16 Operating Mode 를 5 로 두거나, 위험을 알고 --grip-current 0 으로 끌 것")
        else:
            raise SystemExit(f"{get_name} 서비스 없음: Operating Mode 를 확인할 수 없어 중단. 위험을 알고 진행하려면 --grip-current 0")
        if not self.set_goal_current(a.grip_current):
            raise SystemExit(f"ID {a.grip_id} Goal Current 쓰기 실패: 그리퍼를 움직이지 않음")

    def set_goal_current(self, ma):
        """그리퍼 모터 Goal Current(mA) 를 쓴다. 성공 여부를 돌려준다."""
        if self.srv is None or ma <= 0:
            return False
        from dynamixel_interfaces.srv import SetDataToDxl
        req = SetDataToDxl.Request()
        req.id = int(self.a.grip_id)
        req.item_name = "Goal Current"
        req.item_data = int(min(ma, GRIP_CURRENT_MAX))
        res = self._call(self.srv, req, 2.0)
        ok = bool(res is not None and res.result)
        self.node.get_logger().info(f"[{self._tag()}] Goal Current {req.item_data} mA 쓰기: {'OK' if ok else '실패'}")
        return ok

    def send(self, pos, t):
        """클램프한 값을 보낸다. 반환: (보낸 값, 액션 goal future 또는 None)."""
        a = self.a
        p = grip_clamp(a, pos)
        if p != float(pos):
            self.node.get_logger().warn(f"[{self._tag()}] 그리퍼 값 {pos} 를 허용 범위로 자름 -> {p:.3f}")
        if self.mode == "action":
            from control_msgs.action import GripperCommand
            goal = GripperCommand.Goal()
            goal.command.position = p
            goal.command.max_effort = float(a.grip_effort)
            return p, self.client.send_goal_async(goal)
        from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
        from builtin_interfaces.msg import Duration
        m = JointTrajectory()
        m.joint_names = [self.joint]
        m.points = [JointTrajectoryPoint(positions=[p], time_from_start=Duration(sec=int(t), nanosec=int((t - int(t)) * 1e9)))]
        self.pub.publish(m)
        return p, None


def run_plans(a, node, pubs, grippers, plans):
    """plans 를 실제로 실행. 사전위치 -> 하강 -> (보정) -> (잡기 -> 판정 -> 들기 -> 놓기)."""
    import rclpy
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
    from builtin_interfaces.msg import Duration

    def dur(s):
        return Duration(sec=int(s), nanosec=int((s - int(s)) * 1e9))

    def traj(names, pts):
        m = JointTrajectory()
        m.joint_names = names
        m.points = [JointTrajectoryPoint(positions=[float(v) for v in q], time_from_start=dur(t)) for q, t in pts]
        return m

    def wait(sec):
        end = time.time() + sec
        while time.time() < end:
            rclpy.spin_once(node, timeout_sec=0.05)

    def wait_until(fut, sec):
        end = time.time() + sec
        while time.time() < end and not fut.done():
            rclpy.spin_once(node, timeout_sec=0.05)
        return fut.done()

    names = [a.joint_prefix + j for j in JOINTS]
    gjoint = a.joint_prefix + a.gripper_joint

    # /joint_states 구독 (보정과 그리퍼 판정에 공용, node 에 한 번만 만든다)
    if (a.correct > 0 or a.grip) and not hasattr(node, "_js_latest"):
        from sensor_msgs.msg import JointState
        node._js_latest = {}
        for label, ns, _pre, _low, _up in plans:
            topic = with_ns(ns, "joint_states")

            def cb(msg, label=label):
                node._js_latest[label] = dict(zip(msg.name, msg.position))
            node.create_subscription(JointState, topic, cb, 10)

    def read_gripper(label, timeout=1.0):
        """최신 joint_states 에서 그리퍼 위치를 읽는다. 없으면 None."""
        node._js_latest.pop(label, None)
        end = time.time() + timeout
        while time.time() < end:
            rclpy.spin_once(node, timeout_sec=0.05)
            cur = node._js_latest.get(label)
            if cur and gjoint in cur:
                return cur[gjoint]
        return None

    def grip_all(pos, what):
        """모든 팔의 그리퍼를 pos 로 보내고 멈출 때까지 기다린 뒤 {label: (보낸 값, 실제 위치 또는 None, 명령 성공 여부)}.
        액션 모드면 수락과 결과까지 확인한다. 실제 위치는 0.3 초 간격 두 번 읽어 움직임이 멎은 값이다."""
        sent = []
        for label, ns, _pre, _low, _up in plans:
            sent.append((label, ns, *grippers[ns].send(pos, a.t_grip)))
        out = {}
        for label, ns, target, f in sent:
            ok = True
            if f is not None:
                from action_msgs.msg import GoalStatus
                if not wait_until(f, 3.0) or f.result() is None or not f.result().accepted:
                    node.get_logger().error(f"[{label}] 그리퍼 {what} 목표가 수락되지 않음")
                    ok = False
                else:
                    rf = f.result().get_result_async()
                    if wait_until(rf, a.t_grip + 3.0) and rf.result() is not None:
                        r, st = rf.result().result, rf.result().status
                        node.get_logger().info(f"[{label}] 그리퍼 {what} 결과: status {st}, 위치 {r.position:.3f}, 도달 {r.reached_goal}, 막힘 {r.stalled}")
                        if st != GoalStatus.STATUS_SUCCEEDED and not r.stalled:
                            node.get_logger().error(f"[{label}] 그리퍼 {what} 액션 실패 (status {st})")
                            ok = False
                    else:
                        node.get_logger().error(f"[{label}] 그리퍼 {what} 결과 대기 시간 초과")
                        ok = False
            else:
                wait(a.t_grip + 0.3)
            # 멈췄는지 확인: 0.3 초 간격으로 연속 두 번 읽은 값의 차이가 0.01 rad 미만이어야 '안정'. 아니면 None
            cur, stable, end = read_gripper(label), False, time.time() + a.t_grip
            while cur is not None and math.isfinite(cur) and time.time() < end:
                wait(0.3)
                nxt = read_gripper(label)
                if nxt is None or not math.isfinite(nxt):
                    cur = None
                    break
                if abs(nxt - cur) < 0.01:
                    cur, stable = nxt, True
                    break
                cur = nxt
            if not stable:
                node.get_logger().error(f"[{label}] 그리퍼 {what}: 위치가 안정되지 않음 (읽기 실패 또는 계속 움직임)")
                cur = None
            out[label] = (target, cur, ok)
            node.get_logger().info(f"[{label}] 그리퍼 {what}: 명령 {target:.3f}, 실제 {('%.3f' % cur) if cur is not None else '판정 불가'}")
        return out

    def open_all(reason):
        """복구용 열기. 실제로 열림 근처까지 간 것을 확인한다. 실패하면 node._grip_fault 를 세운다."""
        node.get_logger().warn(f"그리퍼 열기 ({reason})")
        got = grip_all(a.grip_open, "열기")
        opened = all(ok and cur is not None and abs(cur - grip_clamp(a, a.grip_open)) < max(a.grip_empty_tol, 0.1)
                     for _t, cur, ok in got.values())
        if not opened:
            node._grip_fault = True
            node.get_logger().error("그리퍼 열기 복구 실패: 모터가 닫힘 목표를 밀고 있을 수 있음. 토크를 풀거나 Wizard 로 확인할 것 "
                                    "(ros2 service call /dynamixel_hardware_interface/set_dxl_torque std_srvs/srv/SetBool '{data: false}')")
        return opened

    deltas = {p[0]: [0.0] * len(JOINTS) for p in plans}

    if a.grip:                               # 내려가기 전에 그리퍼를 연다. 열린 것이 확인되지 않으면 하강하지 않는다
        if not open_all("하강 전"):
            node.get_logger().error("그리퍼 열기 확인 실패: 하강 중단")
            return {p[0]: False for p in plans}
    for label, ns, pre, low, up in plans:    # 같은 루프에서 연달아 publish -> 거의 동시 시작
        pubs[ns].publish(traj(names, [(pre, a.t_pre), (low, a.t_pre + a.t_down)]))
        node.get_logger().info(f"[{label}] 하강 전송")
    wait(a.t_pre + a.t_down + 0.7)
    for it in range(a.correct):              # 처짐 보정: 명령 - 실제 만큼 더 보낸다
        node._js_latest.clear()
        wait(0.6)                            # 새 joint_states 수집
        sent_any = False
        for label, ns, pre, low, up in plans:
            cur = node._js_latest.get(label)
            if not cur or any(n not in cur for n in names):
                node.get_logger().warn(f"[{label}] joint_states 를 못 읽어 보정 건너뜀")
                continue
            err = [low[i] - cur[names[i]] for i in range(len(JOINTS))]
            node.get_logger().info(f"[{label}] 보정 {it + 1}/{a.correct}: 오차 rad = {[round(e, 3) for e in err]}")
            d = deltas[label]
            for i in range(len(JOINTS)):
                d[i] = max(-MAX_CORR, min(MAX_CORR, d[i] + err[i]))
            q = [low[i] + d[i] for i in range(len(JOINTS))]
            pubs[ns].publish(traj(names, [(q, 1.5)]))
            sent_any = True
        if sent_any:
            wait(1.5 + 0.8)

    grasped = {p[0]: True for p in plans}    # --grip 이 아니면 항상 든다
    if not a.grip:
        return lift_and_release(a, node, pubs, plans, names, deltas, grasped, traj, wait, grip_all)
    try:
        got = grip_all(a.grip_close, "닫기")
    except BaseException:                    # Ctrl+C, 통신 예외 등: 닫힘 목표를 남기지 않는다
        open_all("닫기 중 중단")
        raise
    for label, (target, cur, ok) in got.items():
        if not ok:
            grasped[label] = False      # 명령 자체가 거부됨: 들지 않는다 (lift-anyway 도 무시)
            node.get_logger().error(f"[{label}] 닫기 명령 실패: 들지 않음")
            continue
        if cur is None:
            grasped[label] = a.lift_anyway
            node.get_logger().warn(f"[{label}] 그리퍼 위치를 못 읽어 파지 판정 불가" + (" -> 그래도 듦" if a.lift_anyway else " -> 들지 않음"))
            continue
        moved = abs(cur - grip_clamp(a, a.grip_open))
        closed = abs(cur - target) < a.grip_empty_tol
        if moved < a.grip_empty_tol:
            grasped[label] = a.lift_anyway   # 열림 위치에서 거의 안 움직임: 닫기 자체가 안 됨
            node.get_logger().error(f"[{label}] 그리퍼가 닫히지 않음 (실제 {cur:.3f}, 열림 {grip_clamp(a, a.grip_open):.3f})")
        elif closed:
            grasped[label] = a.lift_anyway
            node.get_logger().warn(f"[{label}] 빈손: 끝까지 닫힘 (실제 {cur:.3f}, 닫힘 {target:.3f})"
                                   + (" -> 그래도 듦" if a.lift_anyway else " -> 들지 않음"))
        else:
            grasped[label] = True
            node.get_logger().info(f"[{label}] 파지 성공: 닫힘 전 {abs(cur - target):.3f} rad 에서 멈춤")
    if not any(grasped.values()):        # 아무 팔도 들지 않으면 닫힘 목표를 남기지 않는다
        open_all("파지 실패, 닫힘 목표 해제")
        return grasped
    try:
        return lift_and_release(a, node, pubs, plans, names, deltas, grasped, traj, wait, grip_all)
    except BaseException:
        open_all("들기 중 중단")
        raise


def lift_and_release(a, node, pubs, plans, names, deltas, grasped, traj, wait, grip_all):
    if a.lift_dz > 0:
        lifted = False
        for label, ns, pre, low, up in plans:
            if not grasped[label]:
                continue
            upc = [up[i] + deltas[label][i] for i in range(len(JOINTS))]   # 보정값 유지 (--correct 없으면 0)
            pubs[ns].publish(traj(names, [(upc, a.t_lift)]))
            node.get_logger().info(f"[{label}] 들기 전송")
            lifted = True
        if lifted:
            wait(a.t_lift + 0.7)
    if a.grip and a.release:
        got = grip_all(a.grip_open, "놓기")
        if not all(ok and cur is not None for _t, cur, ok in got.values()):
            node._grip_fault = True
            node.get_logger().error("놓기 확인 실패: 그리퍼 상태를 직접 확인할 것")
    elif a.grip:
        node.get_logger().info("그리퍼는 닫힌 채 유지 (Goal Current 제한 안에서). 열려면 --release 또는 그리퍼 열기 명령")
    return grasped


def main():
    ap = build_parser()
    a = ap.parse_args()

    for name in ("t_pre", "t_down", "t_grip", "t_lift", "pre_dz", "lift_dz"):
        v = getattr(a, name)
        if not math.isfinite(v) or v < 0 or (name.startswith("t_") and v == 0):
            ap.error(f"--{name.replace('_', '-')} 는 유한한 양수여야 함")
    if a.grip:
        missing = [n for n in ("grip_open", "grip_close") if getattr(a, n) is None]
        if missing:
            ap.error("--grip 에는 값이 필요(기본값 없음, 실측): " + ", ".join("--" + m.replace("_", "-") for m in missing))
        vals = [a.grip_open, a.grip_close, a.grip_empty_tol] + (list(a.grip_limit) if a.grip_limit else [])
        if not all(math.isfinite(v) for v in vals):
            ap.error("그리퍼 값(open/close/limit/empty-tol)에 nan 또는 inf 가 있음")
        if a.grip_open == a.grip_close:
            ap.error("--grip-open 과 --grip-close 가 같음")
        if not 0 <= a.grip_current <= GRIP_CURRENT_MAX:
            ap.error(f"--grip-current 는 0~{GRIP_CURRENT_MAX} mA")
        if a.grip_empty_tol <= 0:
            ap.error("--grip-empty-tol 은 0 보다 커야 함")
        if a.both:
            ap.error("--grip 은 한 팔 모드만 지원 (두 팔은 그리퍼 실측값과 모터 설정이 다를 수 있음). 팔마다 따로 실행할 것")
        try:
            grip_bounds(a)
        except SystemExit as e:
            ap.error(str(e))
    if a.both and (a.traj_topic or a.gripper_action or a.dxl_set_srv):
        ap.error("--both 에서는 --traj-topic/--gripper-action/--dxl-set-srv 를 쓸 수 없음 (두 팔이 같은 곳으로 보내짐)")

    jobs = []  # (label, ns, xyz)
    if a.listen:
        if a.both:
            ap.error("--listen 은 한 팔 모드만 지원 (--arm left|right|single)")
        ns = {"left": a.ns_left, "right": a.ns_right, "single": ""}[a.arm]
    elif a.both:
        if not (a.left_xyz and a.right_xyz):
            ap.error("--both 는 --left-xyz 와 --right-xyz 필요")
        jobs = [("left", a.ns_left, a.left_xyz), ("right", a.ns_right, a.right_xyz)]
    else:
        if not a.xyz:
            ap.error("--xyz 또는 --listen 필요")
        ns = {"left": a.ns_left, "right": a.ns_right, "single": ""}[a.arm]
        jobs = [(a.arm, ns, a.xyz)]

    if jobs:
        plans = make_plans(a, jobs)
        if not a.execute:
            print("\n(dry-run) 움직이려면 --execute. 처음엔 팔 주변을 비우고 손은 비상정지 가까이에.")
            return
        if not a.yes:
            input("\n계속하려면 Enter (취소: Ctrl+C) > ")
    elif not a.execute:
        print(f"(dry-run) {a.listen} 를 듣기만 하고 계산 결과만 출력한다. 움직이려면 --execute.")

    if a.execute or a.listen:
        import rclpy
        from rclpy.node import Node
        from trajectory_msgs.msg import JointTrajectory
        rclpy.init()
        node = Node("go_down")
        pubs, grippers = {}, {}
        use_ns = [ns for _, ns, _, _, _ in plans] if jobs else [ns]
        if a.execute:
            pubs = {n: node.create_publisher(JointTrajectory, topic_for(a, n), 10) for n in use_ns}
            t0 = time.time()
            while time.time() - t0 < 5.0 and not all(p.get_subscription_count() > 0 for p in pubs.values()):
                rclpy.spin_once(node, timeout_sec=0.1)
            if not all(p.get_subscription_count() > 0 for p in pubs.values()):
                node.get_logger().error("컨트롤러 구독자 없음: 토픽/네임스페이스 확인 (ros2 topic list | grep trajectory). "
                                        "omx_f_follower_ai.launch 는 --traj-topic /leader/joint_trajectory")
                rclpy.shutdown()
                sys.exit(1)
            if a.grip:
                for n in use_ns:
                    g = Gripper(a, node, n, pubs[n], a.joint_prefix + a.gripper_joint)
                    try:
                        g.setup()
                    except SystemExit as e:
                        node.get_logger().error(str(e))
                        rclpy.shutdown()
                        sys.exit(1)
                    grippers[n] = g

        if jobs:
            run_plans(a, node, pubs, grippers, plans)
        else:
            from geometry_msgs.msg import PointStamped
            box = {"msg": None}

            def on_point(msg):   # 콜백은 저장만. 실제 동작은 아래 루프에서 (콜백 안에서 spin 금지)
                box["msg"] = msg

            node.create_subscription(PointStamped, a.listen, on_point, 1)
            node.get_logger().info(f"{a.listen} 대기 중 (Ctrl+C 종료)")
            try:
                while rclpy.ok():
                    rclpy.spin_once(node, timeout_sec=0.1)
                    msg, box["msg"] = box["msg"], None
                    if msg is None:
                        continue
                    xyz = [msg.point.x, msg.point.y, msg.point.z]
                    node.get_logger().info(f"좌표 수신 {xyz} (frame={msg.header.frame_id})")
                    try:
                        pl = make_plans(a, [(a.arm, ns, xyz)])
                    except SystemExit as e:   # 도달 불가 등: 죽지 말고 건너뜀
                        node.get_logger().warn(f"건너뜀: {e}")
                        continue
                    if a.execute:
                        run_plans(a, node, pubs, grippers, pl)
                        box["msg"] = None     # 동작 중 들어온 좌표는 버림
                        if getattr(node, "_grip_fault", False):
                            node.get_logger().error("그리퍼 복구 실패 상태: 자동 수신을 멈춤. 점검 후 다시 실행")
                            break
            except KeyboardInterrupt:
                pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
