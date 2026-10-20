import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_config = os.path.join(
        get_package_share_directory('uv_to_world'),
        'config',
        'runtime',
        'environment_planes.yaml',
    )
    config = LaunchConfiguration('config')
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=default_config),
        Node(
            package='uv_to_world',
            executable='plane_projection',
            name='entrance_top_uv_to_point',
            output='screen',
            parameters=[config],
        ),
        Node(
            package='uv_to_world',
            executable='plane_projection',
            name='bottom_contact_uv_to_point',
            output='screen',
            parameters=[config],
        ),
    ])
