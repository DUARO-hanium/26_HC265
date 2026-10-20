from lerobot.async_inference.helpers import map_robot_keys_to_lerobot_features

from lerobot_robot_ros2_omx import Ros2Omx, Ros2OmxConfig


def test_training_contract_order_and_shapes():
    robot = Ros2Omx(Ros2OmxConfig(id="test"))
    assert list(robot.action_features) == [
        "joint1.pos", "joint2.pos", "joint3.pos", "joint4.pos", "joint5.pos", "gripper_joint_1.pos"
    ]
    features = map_robot_keys_to_lerobot_features(robot)
    assert features["observation.state"]["shape"] == (6,)
    assert features["observation.images.camera1"]["shape"] == (480, 640, 3)
    assert features["observation.images.camera2"]["shape"] == (480, 640, 3)
