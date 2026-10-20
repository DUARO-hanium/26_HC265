from math import acos, sqrt

import numpy as np


def invert_transform(transform):
    result = np.eye(4)
    rotation = transform[:3, :3]
    result[:3, :3] = rotation.T
    result[:3, 3] = -rotation.T @ transform[:3, 3]
    return result


def project_to_rotation(matrix):
    u, _, vt = np.linalg.svd(matrix)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0.0:
        u[:, -1] *= -1.0
        rotation = u @ vt
    return rotation


def rotation_angle(rotation):
    cosine = max(-1.0, min(1.0, (np.trace(rotation) - 1.0) * 0.5))
    return acos(cosine)


def solve_eye_to_hand(base_to_tool, camera_to_target):
    """Solve base_T_camera from synchronized eye-to-hand pose samples.

    The calibration target is rigidly attached to the tool and the camera is
    fixed with respect to the robot base. Relative motions satisfy AX=XB,
    where X is base_T_camera.
    """
    if len(base_to_tool) != len(camera_to_target) or len(base_to_tool) < 3:
        raise ValueError('at least 3 synchronized pose pairs are required')

    motions = []
    for first in range(len(base_to_tool) - 1):
        for second in range(first + 1, len(base_to_tool)):
            motion_robot = base_to_tool[second] @ invert_transform(base_to_tool[first])
            motion_camera = camera_to_target[second] @ invert_transform(
                camera_to_target[first])
            if rotation_angle(motion_robot[:3, :3]) > 1.0e-4:
                motions.append((motion_robot, motion_camera))
    if len(motions) < 3:
        raise ValueError('insufficient rotational diversity between samples')

    rotation_system = np.vstack([
        np.kron(np.eye(3), robot[:3, :3]) -
        np.kron(camera[:3, :3].T, np.eye(3))
        for robot, camera in motions
    ])
    _, singular_values, vt = np.linalg.svd(rotation_system)
    raw_rotation = vt[-1].reshape((3, 3), order='F')
    if np.linalg.det(raw_rotation) < 0.0:
        raw_rotation = -raw_rotation
    rotation = project_to_rotation(raw_rotation)

    translation_system = np.vstack([
        robot[:3, :3] - np.eye(3) for robot, _ in motions
    ])
    translation_rhs = np.concatenate([
        rotation @ camera[:3, 3] - robot[:3, 3]
        for robot, camera in motions
    ])
    translation, _, rank, _ = np.linalg.lstsq(
        translation_system, translation_rhs, rcond=None)
    if rank < 3:
        raise ValueError('sample motions do not constrain all translation axes')

    result = np.eye(4)
    result[:3, :3] = rotation
    result[:3, 3] = translation
    return result, float(singular_values[-1])


def calibration_residuals(base_to_tool, camera_to_target, base_to_camera):
    """Return per-sample consistency residuals for the fixed tool target."""
    tool_to_targets = [
        invert_transform(robot) @ base_to_camera @ target
        for robot, target in zip(base_to_tool, camera_to_target)
    ]
    mean_translation = np.mean([item[:3, 3] for item in tool_to_targets], axis=0)
    mean_rotation = project_to_rotation(
        sum((item[:3, :3] for item in tool_to_targets), np.zeros((3, 3))))
    translation_errors = np.array([
        np.linalg.norm(item[:3, 3] - mean_translation) for item in tool_to_targets
    ])
    rotation_errors = np.array([
        rotation_angle(mean_rotation.T @ item[:3, :3]) for item in tool_to_targets
    ])
    return translation_errors, rotation_errors


def matrix_to_quaternion(rotation):
    """Convert a rotation matrix to normalized (x, y, z, w)."""
    trace = np.trace(rotation)
    if trace > 0.0:
        scale = sqrt(trace + 1.0) * 2.0
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
        w = 0.25 * scale
    else:
        index = int(np.argmax(np.diag(rotation)))
        if index == 0:
            scale = sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            x = 0.25 * scale
            y = (rotation[0, 1] + rotation[1, 0]) / scale
            z = (rotation[0, 2] + rotation[2, 0]) / scale
            w = (rotation[2, 1] - rotation[1, 2]) / scale
        elif index == 1:
            scale = sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            x = (rotation[0, 1] + rotation[1, 0]) / scale
            y = 0.25 * scale
            z = (rotation[1, 2] + rotation[2, 1]) / scale
            w = (rotation[0, 2] - rotation[2, 0]) / scale
        else:
            scale = sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            x = (rotation[0, 2] + rotation[2, 0]) / scale
            y = (rotation[1, 2] + rotation[2, 1]) / scale
            z = 0.25 * scale
            w = (rotation[1, 0] - rotation[0, 1]) / scale
    quaternion = np.array([x, y, z, w])
    return quaternion / np.linalg.norm(quaternion)
