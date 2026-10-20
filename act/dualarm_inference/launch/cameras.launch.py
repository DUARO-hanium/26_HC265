#!/usr/bin/env python3
"""Three USB cameras, with the official usb_cam defaults and image transport."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import yaml


def setup(context):
    root = Path(LaunchConfiguration('workspace').perform(context))
    device_file = root / 'config/devices.local.yaml'
    if not device_file.exists():
        device_file = root / 'config/devices.yaml'
    devices = yaml.safe_load(device_file.read_text())
    side = LaunchConfiguration('side').perform(context)
    if side not in ('left', 'right', 'both'):
        raise RuntimeError('side must be left/right/both')
    cameras = {k: v for k, v in devices['cameras'].items()
               if side == 'both' or k in ('top', f'wrist_{side}')}
    paths = [c['device'] for c in cameras.values()]
    if any(not p or not Path(p).exists() for p in paths):
        raise RuntimeError('Bind and connect the selected top / wrist cameras first.')
    if len({Path(p).resolve() for p in paths}) != len(paths):
        raise RuntimeError('Each camera needs a distinct capture device.')
    defaults_path = Path(get_package_share_directory('usb_cam')) / 'config/params_1.yaml'
    defaults = next(value['ros__parameters'] for value in yaml.safe_load(defaults_path.read_text()).values()
                    if isinstance(value, dict) and 'ros__parameters' in value)
    nodes = []
    for name, camera in cameras.items():
        ns = f'/camera_{name}'
        nodes.append(Node(
            package='usb_cam', executable='usb_cam_node_exe', namespace=ns,
            name=f'usb_cam_{name}', parameters=[defaults, {
                'video_device': camera['device'], 'image_width': camera['width'],
                'image_height': camera['height'], 'framerate': float(camera['fps']),
                'pixel_format': camera['pixel_format'], 'camera_name': name,
                'frame_id': f'camera_{name}_optical_frame',
                'camera_info_url': camera.get('camera_info_url', ''),
            }], output='screen'))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('workspace', default_value=str(Path(__file__).resolve().parents[1])),
        DeclareLaunchArgument('side', default_value='both'),
        OpaqueFunction(function=setup),
    ])
