#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration
import math
import sys

class MoveToXYZNode(Node):
    def __init__(self, x, y, z):
        super().__init__('move_to_xyz_node')
        self.publisher = self.create_publisher(JointTrajectory, '/arm_controller/joint_trajectory', 10)
        
        joint_angles = self.calculate_ik(x, y, z)
        if joint_angles:
            self.get_logger().info(f"Moving to X={x}, Y={y}, Z={z}")
            self.send_command(joint_angles)
        else:
            self.get_logger().error("Target position is out of reach!")

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

    def send_command(self, joints):
        msg = JointTrajectory()
        msg.joint_names = ['joint1', 'joint2', 'joint3', 'joint4']
        point = JointTrajectoryPoint()
        point.positions = [float(j) for j in joints]
        point.time_from_start = Duration(sec=2, nanosec=0)
        msg.points.append(point)
        self.publisher.publish(msg)

def main():
    if len(sys.argv) < 4:
        print("Usage: python3 src/scripts/move_to_xyz.py [x] [y] [z]")
        return
    
    x, y, z = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    rclpy.init()
    node = MoveToXYZNode(x, y, z)
    rclpy.spin_once(node, timeout_sec=2.0)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
