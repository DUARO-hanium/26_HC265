import math

import pytest

from uv_to_world.geometry import (
    ray_plane_incidence,
    ray_plane_intersection,
    rotate_by_quaternion,
)


def test_ray_hits_ground_plane():
    point = ray_plane_intersection((1.0, 2.0, 3.0), (0.0, 0.0, -1.0),
                                   (0.0, 0.0, 1.0), 0.0)
    assert point == pytest.approx((1.0, 2.0, 0.0))


def test_quaternion_rotation():
    half = math.sqrt(0.5)
    result = rotate_by_quaternion((1.0, 0.0, 0.0), (0.0, 0.0, half, half))
    assert result == pytest.approx((0.0, 1.0, 0.0))


def test_rejects_intersection_behind_camera():
    with pytest.raises(ValueError, match='behind'):
        ray_plane_intersection((0.0, 0.0, 1.0), (0.0, 0.0, 1.0),
                               (0.0, 0.0, 1.0), 0.0)


def test_plane_equation_is_scale_invariant():
    unit = ray_plane_intersection(
        (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0), -2.0)
    scaled = ray_plane_intersection(
        (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), -8.0)
    assert scaled == pytest.approx(unit)


def test_incidence_is_scale_invariant():
    assert ray_plane_incidence(
        (0.0, 0.0, 5.0), (0.0, 0.0, 7.0)) == pytest.approx(1.0)


def test_rejects_non_finite_input():
    with pytest.raises(ValueError, match='finite'):
        ray_plane_intersection(
            (0.0, 0.0, 0.0), (0.0, math.nan, 1.0),
            (0.0, 0.0, 1.0), 0.0)
