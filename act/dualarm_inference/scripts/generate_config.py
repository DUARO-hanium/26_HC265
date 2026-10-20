#!/usr/bin/env python3
"""Compose two official OMX models and emit Cyclo's existing configuration schema."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
ROBOT_TYPE = 'omx_ai_bimanual'
ASSETS = ROOT / 'cyclo_intelligence/shared/shared/robot_configs'


def joint_names(side):
    return [f'{side}_{name}' for name in JOINTS]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def controller_config(side, leader):
    ns = f'/{side}' + ('/leader' if leader else '')
    manager = {'update_rate': 100, 'joint_state_broadcaster': {
        'type': 'joint_state_broadcaster/JointStateBroadcaster'}}
    controllers = {'joint_state_broadcaster': {'use_local_topics': False}}
    if leader:
        manager.update({
            'trigger_position_controller': {'type': 'position_controllers/JointGroupPositionController'},
            'joint_trajectory_command_broadcaster': {
                'type': 'joint_trajectory_command_broadcaster/JointTrajectoryCommandBroadcaster'},
        })
        controllers.update({
            'trigger_position_controller': {'joints': [f'{side}_gripper_joint_1']},
            'joint_trajectory_command_broadcaster': {
                'joints': joint_names(side), 'interfaces': ['position'],
                'reverse_joints': [f'{side}_gripper_joint_1'],
                'offsets': [0.0] * 6, 'use_local_topics': False,
            },
        })
    else:
        manager['arm_controller'] = {'type': 'joint_trajectory_controller/JointTrajectoryController'}
        controllers['arm_controller'] = {
            'joints': joint_names(side), 'interface_name': 'position',
            'command_interfaces': ['position'], 'state_interfaces': ['position', 'velocity'],
            'allow_partial_joints_goal': True,
        }
    result = {f'{ns}/controller_manager': {'ros__parameters': manager}}
    result.update({f'{ns}/{name}': {'ros__parameters': params}
                   for name, params in controllers.items()})
    return result


def combined_urdf(devices):
    source = ET.parse(ASSETS / 'urdf/omx_f.urdf').getroot()
    robot = ET.Element('robot', name=ROBOT_TYPE)
    ET.SubElement(robot, 'link', name='world')
    for side in ('left', 'right'):
        for source_element in source:
            if source_element.tag == 'link' and source_element.get('name') == 'world':
                continue
            element = copy.deepcopy(source_element)
            for node in element.iter():
                for key in ('name', 'link', 'joint'):
                    value = node.get(key)
                    if value and value != 'world':
                        node.set(key, f'{side}_{value}')
            if element.tag == 'joint' and element.get('name') == f'{side}_world_fixed':
                origin = element.find('origin')
                if origin is None:
                    origin = ET.SubElement(element, 'origin')
                for key in ('xyz', 'rpy'):
                    origin.set(key, ' '.join(map(str, devices['base_poses'][side][key])))
            robot.append(element)
    ET.indent(robot)
    ET.ElementTree(robot).write(ASSETS / 'urdf/omx_ai_bimanual.urdf',
                               encoding='utf-8', xml_declaration=True)


def main():
    device_file = ROOT / 'config/devices.local.yaml'
    if not device_file.exists():
        device_file = ROOT / 'config/devices.yaml'
    devices = yaml.safe_load(device_file.read_text())
    initial = yaml.safe_load((ROOT / 'open_manipulator/open_manipulator_bringup/config/'
                              'omx_f_follower_ai/initial_positions.yaml').read_text())
    for side in ('left', 'right'):
        for role in ('leader', 'follower'):
            dump(ROOT / f'config/generated/{side}_{role}_controllers.yaml',
                 controller_config(side, leader=role == 'leader'))
        params = copy.deepcopy(initial['joint_trajectory_executor']['ros__parameters'])
        params.update(joint_names=joint_names(side),
                      action_topic=f'/{side}/arm_controller/follow_joint_trajectory',
                      joint_states_topic=f'/{side}/joint_states')
        dump(ROOT / f'config/generated/{side}_initial_positions.yaml',
             {f'/{side}/joint_trajectory_executor': {'ros__parameters': params}})

    section = {
        'robot_name': 'OMX-AI Bimanual (2 Leaders + 2 Followers)',
        'urdf_path': 'urdf/omx_ai_bimanual.urdf',
        'visualization': {'end_effector_links': ['left_end_effector_link', 'right_end_effector_link']},
        'observation': {'images': {}, 'state': {}},
        'action': {},
        'recording': {'extra_topics': ['/tf']},
    }
    for name, camera in devices['cameras'].items():
        section['observation']['images'][name] = {
            'topic': f'/camera_{name}/image_raw/compressed',
            'msg_type': 'sensor_msgs/msg/CompressedImage',
            'rotation_deg': camera['rotation_deg'],
        }
        section['recording']['extra_topics'].append(f'/camera_{name}/camera_info')
    for side in ('left', 'right'):
        section['observation']['state'][f'arm_{side}'] = {
            'topic': f'/{side}/joint_states', 'msg_type': 'sensor_msgs/msg/JointState',
            'joint_names': joint_names(side),
        }
        section['action'][f'arm_{side}'] = {
            'topic': f'/{side}/leader/joint_trajectory',
            'msg_type': 'trajectory_msgs/msg/JointTrajectory', 'joint_names': joint_names(side),
        }
    combined_urdf(devices)
    for side in ('left', 'right'):
        single = copy.deepcopy(section)
        single['robot_name'] = f'OMX-AI {side.title()} (ACT / single-arm collection)'
        single['visualization']['end_effector_links'] = [f'{side}_end_effector_link']
        # A separate state group makes RobotClient order values by joint name.
        single['observation']['state'] = {'joints': section['observation']['state'][f'arm_{side}']}
        single['action'] = {'arm': section['action'][f'arm_{side}']}
        single['observation']['images'] = {
            'top': section['observation']['images']['top'],
            'wrist': section['observation']['images'][f'wrist_{side}'],
        }
        single['recording']['extra_topics'] = [
            '/tf', '/camera_top/camera_info', f'/camera_wrist_{side}/camera_info']
        name = f'omx_ai_{side}'
        dump(ASSETS / f'{name}_config.yaml', {'orchestrator': {'ros__parameters': {name: single}}})
    print('Generated omx_ai_left / omx_ai_right: 6 radian joints, top + wrist images each.')


if __name__ == '__main__':
    main()
