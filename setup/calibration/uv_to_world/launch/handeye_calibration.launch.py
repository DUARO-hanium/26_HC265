import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('uv_to_world'),
        'config',
        'calibration',
        'handeye_calibration.yaml',
    )
    return LaunchDescription([
        Node(package='uv_to_world', executable='handeye_calibrator',
             name='handeye_calibrator', output='screen', parameters=[config]),
    ])
