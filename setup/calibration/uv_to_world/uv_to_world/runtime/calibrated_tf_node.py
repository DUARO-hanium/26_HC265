import os
from math import isfinite, sqrt

from geometry_msgs.msg import TransformStamped
import rclpy
from rclpy.node import Node
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
import yaml


def validate_calibration(document):
    if not isinstance(document, dict) or not isinstance(
            document.get('calibration'), dict):
        raise ValueError('missing calibration mapping')
    calibration = document['calibration']
    if calibration.get('quality_passed') is not True:
        raise ValueError('calibration quality did not pass')

    parent = calibration.get('parent_frame')
    child = calibration.get('child_frame')
    if not isinstance(parent, str) or not parent.strip():
        raise ValueError('parent_frame must be a non-empty string')
    if not isinstance(child, str) or not child.strip():
        raise ValueError('child_frame must be a non-empty string')
    if parent == child:
        raise ValueError('parent_frame and child_frame must differ')

    translation = calibration.get('translation')
    quaternion = calibration.get('quaternion_xyzw')
    if not isinstance(translation, (list, tuple)) or len(translation) != 3:
        raise ValueError('translation must contain exactly 3 values')
    if not isinstance(quaternion, (list, tuple)) or len(quaternion) != 4:
        raise ValueError('quaternion_xyzw must contain exactly 4 values')
    try:
        translation = [float(value) for value in translation]
        quaternion = [float(value) for value in quaternion]
    except (TypeError, ValueError) as error:
        raise ValueError('transform values must be numeric') from error
    if not all(isfinite(value) for value in translation + quaternion):
        raise ValueError('transform values must be finite')

    norm = sqrt(sum(value * value for value in quaternion))
    if norm < 1e-12:
        raise ValueError('quaternion norm must be non-zero')
    if abs(norm - 1.0) > 1e-3:
        raise ValueError(
            f'quaternion must be normalized (observed norm {norm:.6f})')

    validated = dict(calibration)
    validated['parent_frame'] = parent.strip()
    validated['child_frame'] = child.strip()
    validated['translation'] = translation
    validated['quaternion_xyzw'] = [value / norm for value in quaternion]
    return validated


class CalibratedTfPublisher(Node):
    def __init__(self):
        super().__init__('calibrated_camera_tf')
        self.declare_parameter(
            'calibration_file', '~/.ros/uv_to_world/eye_to_hand.yaml')
        path = os.path.expanduser(self.get_parameter('calibration_file').value)
        with open(path, encoding='utf-8') as stream:
            calibration = validate_calibration(yaml.safe_load(stream))
        message = TransformStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = calibration['parent_frame']
        message.child_frame_id = calibration['child_frame']
        translation = calibration['translation']
        quaternion = calibration['quaternion_xyzw']
        message.transform.translation.x = translation[0]
        message.transform.translation.y = translation[1]
        message.transform.translation.z = translation[2]
        message.transform.rotation.x = quaternion[0]
        message.transform.rotation.y = quaternion[1]
        message.transform.rotation.z = quaternion[2]
        message.transform.rotation.w = quaternion[3]
        self._broadcaster = StaticTransformBroadcaster(self)
        self._broadcaster.sendTransform(message)
        self.get_logger().info(
            f'Published calibrated TF {message.header.frame_id} -> '
            f'{message.child_frame_id} from {path}')


def main(args=None):
    rclpy.init(args=args)
    node = CalibratedTfPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
