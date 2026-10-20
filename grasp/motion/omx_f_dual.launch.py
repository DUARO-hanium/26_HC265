"""
omx_f 두 대를 left/right 네임스페이스로 띄우는 launch (실기 미검증).

  ros2 launch ./omx_f_dual.launch.py left_port:=/dev/ttyACM0 right_port:=/dev/ttyACM1

- 포트 인자 이름: 팀 README 예시(omx_f.launch.py usb_port:=/dev/ttyACM0)를 근거로 usb_port 로 설정. 다르면 아래에서 수정.
- 네임스페이스는 토픽/노드에만 붙고 /tf 프레임 이름(link0 등)은 그대로라서, 두 팔 TF 가 섞이는지 실기에서 확인해야 한다.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    bringup = get_package_share_directory("open_manipulator_bringup")
    omx_f = os.path.join(bringup, "launch", "omx_f.launch.py")

    def arm(ns, port_arg):
        return GroupAction([
            PushRosNamespace(ns),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(omx_f),
                launch_arguments={"usb_port": LaunchConfiguration(port_arg)}.items(),
            ),
        ])

    return LaunchDescription([
        DeclareLaunchArgument("left_port", default_value="/dev/ttyACM0"),
        DeclareLaunchArgument("right_port", default_value="/dev/ttyACM1"),
        arm("left", "left_port"),
        arm("right", "right_port"),
    ])
