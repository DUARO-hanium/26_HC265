import numpy as np
import pytest

from conversion.convert_dataset import (
    JOINTS,
    MAX_INTERPOLATION_GAP_NS,
    NumericStream,
    canonical_joint_vector,
    episode_paths,
    interpolate_bounded,
    parse_episodes,
    strictly_monotonic_pairs,
)


def test_joint_values_are_reordered_by_name():
    names = ["joint3", "gripper_joint_1", "joint1", "joint5", "joint2", "joint4"]
    values = [3.0, 6.0, 1.0, 5.0, 2.0, 4.0]
    assert JOINTS == ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
    np.testing.assert_array_equal(canonical_joint_vector(names, values), np.arange(1, 7))


def test_regression_drops_timestamp_value_pair():
    timestamps, values, drops = strictly_monotonic_pairs([10, 20, 19, 30], ["a", "b", "c", "d"])
    np.testing.assert_array_equal(timestamps, [10, 20, 30])
    assert values == ["a", "b", "d"]
    assert drops == 1


def test_linear_interpolation_is_bounded_and_bracketed():
    stream = NumericStream(
        np.array([0, 60_000_000], dtype=np.int64),
        np.array([[0.0] * 6, [6.0] * 6], dtype=np.float32),
        raw_count=2,
        regression_drops=0,
    )
    value, label = interpolate_bounded(stream, 30_000_000)
    np.testing.assert_allclose(value, [3.0] * 6)
    assert label == "short_interpolation"
    assert interpolate_bounded(stream, -1)[0] is None


def test_gap_over_100ms_is_never_interpolated():
    stream = NumericStream(
        np.array([0, MAX_INTERPOLATION_GAP_NS + 1], dtype=np.int64),
        np.array([[0.0] * 6, [1.0] * 6], dtype=np.float32),
        raw_count=2,
        regression_drops=0,
    )
    value, label = interpolate_bounded(stream, 50_000_000)
    assert value is None
    assert label == "long_gap"


def test_episode_range_and_portable_layout(tmp_path):
    assert parse_episodes("0-2,5") == [0, 1, 2, 5]
    paths = episode_paths(tmp_path, 5, "Task_demo_{episode:02d}_MCAP/0")
    assert paths["mcap"] == tmp_path / "Task_demo_05_MCAP/0/0_0.mcap"
    with pytest.raises(ValueError, match="stay below"):
        episode_paths(tmp_path, 5, "../outside/{episode}")
