from math import cos, sin

import numpy as np
import pytest

from uv_to_world.calibration_math import (
    calibration_residuals,
    invert_transform,
    matrix_to_quaternion,
    solve_eye_to_hand,
)


def transform(axis, angle, translation):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    cross = np.array([[0, -axis[2], axis[1]],
                      [axis[2], 0, -axis[0]],
                      [-axis[1], axis[0], 0]])
    rotation = np.eye(3) + sin(angle) * cross + (1 - cos(angle)) * (cross @ cross)
    result = np.eye(4)
    result[:3, :3] = rotation
    result[:3, 3] = translation
    return result


def synthetic_samples():
    base_to_camera = transform([1, 2, 3], 0.7, [0.4, -0.2, 0.6])
    tool_to_target = transform([2, -1, 1], -0.4, [0.02, 0.0, 0.08])
    robots = []
    targets = []
    for index in range(15):
        robot = transform(
            [1 + index % 3, 2 + index % 4, 1 + index % 5],
            -0.8 + 0.12 * index,
            [0.18 + 0.012 * index, -0.12 + 0.018 * index, 0.2 + 0.006 * index])
        robots.append(robot)
        targets.append(invert_transform(base_to_camera) @ robot @ tool_to_target)
    return base_to_camera, robots, targets


def test_eye_to_hand_solver_recovers_exact_transform():
    expected, robots, targets = synthetic_samples()
    actual, _ = solve_eye_to_hand(robots, targets)
    assert actual == pytest.approx(expected, abs=1.0e-9)
    translation, rotation = calibration_residuals(robots, targets, actual)
    assert max(translation) < 1.0e-9
    assert max(rotation) < 1.0e-7


def test_matrix_to_quaternion_is_normalized():
    expected, _, _ = synthetic_samples()
    quaternion = matrix_to_quaternion(expected[:3, :3])
    assert np.linalg.norm(quaternion) == pytest.approx(1.0)


def test_solver_rejects_repeated_pose():
    repeated = [np.eye(4) for _ in range(5)]
    with pytest.raises(ValueError, match='rotational diversity'):
        solve_eye_to_hand(repeated, repeated)
