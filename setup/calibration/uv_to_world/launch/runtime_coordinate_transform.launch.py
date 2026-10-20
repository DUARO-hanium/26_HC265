from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    calibration_dir = LaunchConfiguration('calibration_dir')
    eye_to_hand = PathJoinSubstitution([calibration_dir, 'eye_to_hand.yaml'])
    environment_planes = PathJoinSubstitution([
        calibration_dir,
        'environment_planes.yaml',
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            'calibration_dir',
            description=(
                'Calibration bundle containing eye_to_hand.yaml and '
                'environment_planes.yaml.'
            ),
        ),
        Node(
            package='uv_to_world',
            executable='calibrated_tf_publisher',
            name='calibrated_camera_tf',
            output='screen',
            parameters=[{'calibration_file': eye_to_hand}],
        ),
        Node(
            package='uv_to_world',
            executable='plane_projection',
            name='entrance_top_uv_to_point',
            output='screen',
            parameters=[environment_planes],
        ),
        Node(
            package='uv_to_world',
            executable='plane_projection',
            name='bottom_contact_uv_to_point',
            output='screen',
            parameters=[environment_planes],
        ),
    ])
