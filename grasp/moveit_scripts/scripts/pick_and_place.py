#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration
import math
import time
import sys

class OpenManipulatorController(Node):
    def __init__(self):
        super().__init__('open_manipulator_controller')
        self.arm_pub = self.create_publisher(JointTrajectory, '/arm_controller/joint_trajectory', 10)
        self.gripper_pub = self.create_publisher(JointTrajectory, '/gripper_controller/joint_trajectory', 10)
        time.sleep(1.0)

    def calculate_ik(self, x, y, z):
        l1, l2, l3 = 0.128, 0.130, 0.124
        try:
            j1 = math.atan2(y, x)
            r = math.sqrt(x**2 + y**2)
            z_eff = z - l1
            cos_j3 = (r**2 + z_eff**2 - l2**2 - l3**2) / (2 * l2 * l3)
            j3 = math.atan2(math.sqrt(1 - cos_j3**2), cos_j3)
            j2 = math.atan2(z_eff, r) - math.atan2(l3 * math.sin(j3), l2 + l3 * math.cos(j3))
            j4 = -(j2 + j3)
            return [j1, -j2, j3, j4]
        except:
            return None

    def move_arm(self, joints, duration_sec=3.0):
        msg = JointTrajectory()
        msg.joint_names = ['joint1', 'joint2', 'joint3', 'joint4']
        point = JointTrajectoryPoint()
        point.positions = [float(j) for j in joints]
        point.time_from_start = Duration(sec=int(duration_sec), nanosec=0)
        msg.points.append(point)
        self.arm_pub.publish(msg)
        time.sleep(duration_sec + 0.5)

    def control_gripper(self, position, duration_sec=1.5):
        msg = JointTrajectory()
        msg.joint_names = ['gripper']
        point = JointTrajectoryPoint()
        point.positions = [float(position)]
        point.time_from_start = Duration(sec=int(duration_sec), nanosec=0)
        msg.points.append(point)
        self.gripper_pub.publish(msg)
        time.sleep(duration_sec + 0.5)

def main():
    if len(sys.argv) < 4:
        print("Usage: python3 src/scripts/pick_and_place.py [X] [Y] [Z]")
        return

    target_x = float(sys.argv[1])
    target_y = float(sys.argv[2])
    target_z = float(sys.argv[3])

    rclpy.init()
    bot = OpenManipulatorController()

    print(f"=== [1/3] 목표 좌표 (X={target_x}, Y={target_y}, Z={target_z}) IK 계산 ===")
    joints = bot.calculate_ik(target_x, target_y, target_z)
    if not joints:
        print("❌ 도달할 수 없는 위치입니다.")
        rclpy.shutdown()
        return

    print("=== [2/3] 그리퍼 미리 열기 & 목표 위치로 이동 ===")
    bot.control_gripper(0.01)
    bot.move_arm(joints, duration_sec=3.0)

    print("=== [3/3] 목표 위치 도착 후 그리퍼 닫기 (집기) ===")
    bot.control_gripper(-0.01)

    print("✅ Pick 동작 완료!")
    bot.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
