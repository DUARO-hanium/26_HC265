#!/usr/bin/env python3
"""
봉지 안쪽 진입 Motion Planning 스크립트

연동 구조:
    uv_to_world 패키지
    → /package/entrance_top_point 토픽 발행 (geometry_msgs/PointStamped)
    → 이 스크립트가 그 값을 구독해서 entry_xyz로 사용

    bag_insertion.py
    → entry_xyz(봉지 입구) → waypoint(방향 전환) → target_xyz(옷 위치)
      순서로 waypoint를 하나씩 순차 plan+execute

⚠️ 미해결 상태 (실측/추가 구현 필요):
    - waypoint_xyz : 그리퍼가 완전히 아래를 향하게 되는 지점 (placeholder)
    - target_xyz   : 옷 위치, 현재 uv_to_world 범위 밖 (별도 vision 필요)
    - moveit_cpp_config.yaml 경로는 실행 환경에 맞게 수정 필요
    - plan_cartesian_path()가 이 MoveItPy 버전(Jazzy)에 없어서
      waypoint를 하나씩 순차 실행하는 방식으로 대체함
      (troubleshooting/moveit_py.md 참고)
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose, PoseStamped, PointStamped
from moveit_configs_utils import MoveItConfigsBuilder
from tf_transformations import quaternion_from_euler
import numpy as np

from moveit.planning import MoveItPy


def make_pose(x, y, z, roll, pitch, yaw):
    """위치(x,y,z) + 회전(roll,pitch,yaw, 라디안)으로 Pose 생성"""
    pose = Pose()
    pose.position.x = x
    pose.position.y = y
    pose.position.z = z
    q = quaternion_from_euler(roll, pitch, yaw)
    pose.orientation.x = q[0]
    pose.orientation.y = q[1]
    pose.orientation.z = q[2]
    pose.orientation.w = q[3]
    return pose


def build_waypoints(entry_xyz, waypoint_xyz, target_xyz,
                     entry_pitch, waypoint_pitch, n_curve_points=4):
    """
    entry_xyz     : 봉지 입구 world 좌표 (uv_to_world에서 실시간 수신)
    waypoint_xyz  : 그리퍼가 완전히 아래를 향하게 되는 지점 (⚠️ placeholder, 실측 필요)
    target_xyz    : 옷 위치 (⚠️ placeholder, 별도 vision 필요)
    entry_pitch   : 시작 시 그리퍼 기울기 (0.0 = 수평)
    waypoint_pitch: waypoint에서 그리퍼 기울기 (-1.57 = 아래 90도)

    반환: 순차 실행할 Pose 리스트
          (Phase1: entry->waypoint 곡선+회전, Phase2: waypoint->target 직진)
    """
    waypoints = []

    # ── Phase 1: entry -> waypoint, 위치 선형보간 + pitch 선형보간 ──
    # z에 sin 곡선을 더해 아치형(둥글게) 궤적을 근사
    for i in range(1, n_curve_points + 1):
        t = i / n_curve_points

        x = entry_xyz[0] + (waypoint_xyz[0] - entry_xyz[0]) * t
        y = entry_xyz[1] + (waypoint_xyz[1] - entry_xyz[1]) * t
        z = entry_xyz[2] + (waypoint_xyz[2] - entry_xyz[2]) * t \
            + 0.02 * np.sin(np.pi * t)  # 아치 높이 0.02m, 실측 후 조정 필요

        pitch = entry_pitch + (waypoint_pitch - entry_pitch) * t
        waypoints.append(make_pose(x, y, z, 0.0, pitch, 0.0))

    # ── Phase 2: waypoint -> target, orientation 고정한 채 직진 ──
    waypoints.append(make_pose(
        target_xyz[0], target_xyz[1], target_xyz[2],
        0.0, waypoint_pitch, 0.0
    ))

    return waypoints


class BagInsertionNode(Node):
    def __init__(self, moveit, arm, gripper):
        super().__init__('bag_insertion')

        self.entry_point = None  # uv_to_world에서 받은 entrance_top_point 저장
        self.moveit = moveit
        self.arm = arm
        self.gripper = gripper

        # uv_to_world 패키지가 발행하는 토픽 구독
        self.create_subscription(
            PointStamped,
            '/package/entrance_top_point',
            self._entry_point_callback,
            10
        )

    def _entry_point_callback(self, msg: PointStamped):
        """uv_to_world에서 좌표가 들어올 때마다 저장"""
        self.entry_point = (msg.point.x, msg.point.y, msg.point.z)
        self.get_logger().info(f"entry point 수신: {self.entry_point}")

    def run_insertion(self):
        if self.entry_point is None:
            self.get_logger().warn("entry point 미수신, placeholder 값으로 진행")
            entry_xyz = (0.15, 0.0, 0.15)  # ⚠️ placeholder
        else:
            entry_xyz = self.entry_point

        # ⚠️ 아래 두 값은 여전히 placeholder (실측/별도 vision 필요)
        waypoint_xyz = (0.18, 0.0, 0.10)
        target_xyz = (0.20, 0.0, 0.05)

        entry_pitch = 0.0
        waypoint_pitch = -1.0

        waypoints = build_waypoints(
            entry_xyz, waypoint_xyz, target_xyz,
            entry_pitch, waypoint_pitch,
            n_curve_points=4
        )

        # ── plan_cartesian_path가 없어서 waypoint를 하나씩 순차 실행 ──
        for i, wp in enumerate(waypoints):
            self.arm.set_start_state_to_current_state()

            wp_stamped = PoseStamped()
            wp_stamped.header.frame_id = "world"
            wp_stamped.pose = wp

            self.arm.set_goal_state(pose_stamped_msg=wp_stamped, pose_link="end_effector_link")

            plan_result = self.arm.plan()
            if plan_result:
                self.get_logger().info(f"waypoint {i+1}/{len(waypoints)} 계획 성공, 실행 중...")
                self.moveit.execute(plan_result.trajectory, controllers=[])
            else:
                self.get_logger().warn(f"waypoint {i+1}/{len(waypoints)} 계획 실패, 중단")
                return

        self.get_logger().info("전체 경로 실행 완료!")

        # ── 그리퍼 닫기 (옷 집기) ──
        self.gripper.set_goal_state(configuration_name="gripper_zero")
        gripper_plan = self.gripper.plan()
        if gripper_plan:
            self.moveit.execute(gripper_plan.trajectory, controllers=[])


def main():
    rclpy.init()

    # ⚠️ moveit_cpp_config.yaml 경로는 실행 환경에 맞게 수정 필요
    moveit_config = (
        MoveItConfigsBuilder("omx_l", package_name="omx_l")
        .moveit_cpp(file_path="/home/ap432/moveit_cpp_config.yaml")
        .to_moveit_configs()
        .to_dict()
    )

    moveit = MoveItPy(node_name="bag_insertion_moveit", config_dict=moveit_config)
    arm = moveit.get_planning_component("arm")
    gripper = moveit.get_planning_component("gripper")

    node = BagInsertionNode(moveit, arm, gripper)
    node.run_insertion()

    rclpy.spin(node)


if __name__ == '__main__':
    main()
