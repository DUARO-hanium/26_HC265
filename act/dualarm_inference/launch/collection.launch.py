#!/usr/bin/env python3
"""Start one teleoperation pair, top and wrist cameras, with optional other-arm hold."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    directory = Path(__file__).resolve().parent
    return LaunchDescription([
        DeclareLaunchArgument('side', default_value='left'),
        DeclareLaunchArgument('hold_other', default_value='false'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(directory / 'teleop.launch.py')),
                                 launch_arguments={'side': LaunchConfiguration('side'),
                                                   'hold_other': LaunchConfiguration('hold_other')}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(directory / 'cameras.launch.py')),
                                 launch_arguments={'side': LaunchConfiguration('side')}.items()),
    ])
