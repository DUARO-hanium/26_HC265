#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration
import sys

class GripperControlNode(Node):
    def __init__(self, action):
        super().__init__('gripper_control_node')
        self.publisher = self.create_publisher(JointTrajectory, '/gripper_controller/joint_trajectory', 10)
        
        if action == 'open':
            target_pos = 0.01
        elif action == 'close':
            target_pos = -0.01
        else:
            try:
                target_pos = float(action)
            except ValueError:
                self.get_logger().error("Invalid action! Use 'open', 'close', or float.")
                return

        self.send_gripper_command(target_pos)

    def send_gripper_command(self, position):
        msg = JointTrajectory()
        msg.joint_names = ['gripper']
        point = JointTrajectoryPoint()
        point.positions = [float(position)]
        point.time_from_start = Duration(sec=1, nanosec=0)
        msg.points.append(point)
        self.publisher.publish(msg)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 src/scripts/gripper_control.py [open|close|position_val]")
        return
    
    action = sys.argv[1].lower()
    rclpy.init()
    node = GripperControlNode(action)
    rclpy.spin_once(node, timeout_sec=1.5)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
