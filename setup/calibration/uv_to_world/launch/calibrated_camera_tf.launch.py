from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'calibration_file',
            default_value='~/.ros/uv_to_world/eye_to_hand.yaml'),
        Node(package='uv_to_world', executable='calibrated_tf_publisher',
             name='calibrated_camera_tf', output='screen', parameters=[{
                 'calibration_file': LaunchConfiguration('calibration_file')}]),
    ])
