#!/usr/bin/env python3
"""Two OMX-AI pairs using ROBOTIS hardware, controllers and initialization."""
from pathlib import Path
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, ExecuteProcess, LogInfo, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
import xacro
import yaml


def setup(context):
    root = Path(LaunchConfiguration('workspace').perform(context))
    mock = LaunchConfiguration('use_mock_hardware').perform(context).lower() == 'true'
    selected = LaunchConfiguration('side').perform(context)
    mode = LaunchConfiguration('mode').perform(context)
    if selected not in ('left', 'right', 'both') or mode not in ('teleop', 'inference'):
        raise RuntimeError('side must be left/right/both; mode must be teleop/inference')
    hold_other = LaunchConfiguration('hold_other').perform(context).lower() == 'true'
    sides = ('left', 'right') if selected == 'both' or hold_other else (selected,)
    roles_by_side = {s: (('follower', 'leader') if mode == 'teleop' and selected in (s, 'both')
                         else ('follower',)) for s in sides}
    device_file = root / 'config/devices.local.yaml'
    if not device_file.exists():
        device_file = root / 'config/devices.yaml'
    devices = yaml.safe_load(device_file.read_text())
    if not mock:
        ports = [devices['serial'][f'{s}_{r}'] for s in sides for r in roles_by_side[s]]
        if any(not p or not Path(p).exists() for p in ports):
            raise RuntimeError('Bind and connect the selected serial devices before hardware launch.')
        if len({Path(p).resolve() for p in ports}) != len(ports):
            raise RuntimeError('Every leader and follower must have its own USB device.')
    description_dir = Path(get_package_share_directory('open_manipulator_description'))
    ready = set()
    leaders = []
    actions = []

    def fail(reason):
        return [LogInfo(msg=reason), EmitEvent(event=Shutdown(reason=reason))]

    def prepare_complete(side):
        def callback(event, _context):
            if event.returncode != 0:
                return fail(f'{side}: follower preparation failed; leaders will not start.')
            ready.add(side)
            if len(ready) == len(sides):
                return [LogInfo(msg='Selected followers ready. Starting leaders only in teleop mode.'), *leaders]
            return [LogInfo(msg=f'{side}: follower prepared; waiting for the other arm.')]
        return callback

    for side in sides:
        for role in roles_by_side[side]:
            ns = f'/{side}' + ('/leader' if role == 'leader' else '')
            model = 'omx_l' if role == 'leader' else 'omx_f'
            document = xacro.process_file(
                str(description_dir / f'urdf/{model}/{model}.urdf.xacro'),
                mappings={'prefix': f'{side}_', 'use_sim': 'false',
                          'use_mock_hardware': str(mock).lower(),
                          'port_name': devices['serial'][f'{side}_{role}'] or '/dev/unused',
                          'ros2_control_type': model})
            urdf = ET.fromstring(document.toxml())
            origin = urdf.find(f"joint[@name='{side}_world_fixed']/origin")
            for key in ('xyz', 'rpy'):
                origin.set(key, ' '.join(map(str, devices['base_poses'][side][key])))
            robot_description = ParameterValue(ET.tostring(urdf, encoding='unicode'), value_type=str)
            controllers = str(root / f'config/generated/{side}_{role}_controllers.yaml')
            control = Node(
                package='controller_manager', executable='ros2_control_node',
                namespace=ns, parameters=[{'robot_description': robot_description}, controllers],
                output='screen')
            state = Node(
                package='robot_state_publisher', executable='robot_state_publisher',
                namespace=ns, parameters=[{'robot_description': robot_description,
                                         'frame_prefix': 'leader_' if role == 'leader' else ''}],
                output='screen')
            names = ['joint_state_broadcaster', 'trigger_position_controller',
                     'joint_trajectory_command_broadcaster'] if role == 'leader' else [
                         'arm_controller', 'joint_state_broadcaster']
            remap = f'/collision_flag:=/{side}/collision_flag' if role == 'leader' else (
                f'/{side}/arm_controller/joint_trajectory:=/{side}/leader/joint_trajectory')
            spawner = Node(
                package='controller_manager', executable='spawner', namespace=ns,
                arguments=[*names, '--controller-manager', f'{ns}/controller_manager',
                           '--param-file', controllers, '--controller-manager-timeout', '90',
                           f'--controller-ros-args=--ros-args -r {remap}'],
                output='screen')
            control_exit = RegisterEventHandler(OnProcessExit(
                target_action=control,
                on_exit=lambda event, ctx, ns=ns: fail(f'{ns}: controller manager stopped.')))
            if role == 'leader':
                trigger = ExecuteProcess(cmd=[
                    'ros2', 'topic', 'pub', '-r', '50', '-p', '50',
                    f'{ns}/trigger_position_controller/commands',
                    'std_msgs/msg/Float64MultiArray', 'data: [-0.7]'], output='log')

                def leader_spawned(event, _context, trigger=trigger, ns=ns):
                    return [trigger] if event.returncode == 0 else fail(f'{ns}: controllers failed.')

                leaders.extend([control_exit, RegisterEventHandler(OnProcessExit(
                    target_action=spawner, on_exit=leader_spawned)), control, state, spawner])
            else:
                executor = Node(
                    package='open_manipulator_bringup', executable='joint_trajectory_executor',
                    namespace=ns, parameters=[str(root / f'config/generated/{side}_initial_positions.yaml')],
                    output='screen')
                complete = prepare_complete(side)

                def follower_spawned(event, _context, executor=executor, complete=complete, side=side):
                    if event.returncode != 0 or mock or 'leader' not in roles_by_side[side]:
                        return complete(event, _context)
                    return [executor]

                actions.extend([control_exit, RegisterEventHandler(OnProcessExit(
                    target_action=spawner, on_exit=follower_spawned)),
                    RegisterEventHandler(OnProcessExit(target_action=executor, on_exit=complete)),
                    control, state, spawner])
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('workspace', default_value=str(Path(__file__).resolve().parents[1])),
        DeclareLaunchArgument('use_mock_hardware', default_value='false'),
        DeclareLaunchArgument('side', default_value='both'),
        DeclareLaunchArgument('mode', default_value='teleop'),
        DeclareLaunchArgument('hold_other', default_value='false'),
        OpaqueFunction(function=setup),
    ])
