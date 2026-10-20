#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration

class GoHomeNode(Node):
    def __init__(self):
        super().__init__('go_home')
        self.publisher = self.create_publisher(JointTrajectory, '/arm_controller/joint_trajectory', 10)
        
        msg = JointTrajectory()
        msg.joint_names = ['joint1', 'joint2', 'joint3', 'joint4']
        point = JointTrajectoryPoint()
        point.positions = [0.0, 0.0, 0.0, 0.0]
        point.time_from_start = Duration(sec=3, nanosec=0)
        msg.points.append(point)
        
        self.publisher.publish(msg)

def main():
    rclpy.init()
    node = GoHomeNode()
    rclpy.spin_once(node, timeout_sec=3.5)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
