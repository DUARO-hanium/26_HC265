from math import isfinite

from geometry_msgs.msg import PointStamped
from image_geometry import PinholeCameraModel
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo
from tf2_ros import Buffer, TransformException, TransformListener

from .geometry import (
    ray_plane_incidence,
    ray_plane_intersection,
    rotate_by_quaternion,
)


def pixel_to_camera_ray(model, pixel, uv_is_rectified):
    """Return a camera ray from either raw or rectified pixel coordinates."""
    if not uv_is_rectified:
        pixel = model.rectify_point(pixel)
    return model.project_pixel_to_3d_ray(pixel)


class PlaneProjectionNode(Node):
    def __init__(self):
        super().__init__('plane_projection')
        self.declare_parameter('plane_name', 'unknown')
        self.declare_parameter('target_frame', 'link0')
        self.declare_parameter('camera_info_topic', '/camera/camera_info')
        self.declare_parameter('uv_topic', '/uv_point')
        self.declare_parameter('output_topic', '/world_point')
        self.declare_parameter('uv_is_rectified', True)
        self.declare_parameter('plane_normal', [0.0, 0.0, 1.0])
        self.declare_parameter('plane_offset', 0.0)
        self.declare_parameter('minimum_incidence', 0.05)
        self.declare_parameter('calibration_valid', False)
        self.declare_parameter('uv_qos_reliability', 'best_effort')

        normal = self.get_parameter('plane_normal').value
        offset = float(self.get_parameter('plane_offset').value)
        incidence = float(self.get_parameter('minimum_incidence').value)
        if not self.get_parameter('calibration_valid').value:
            raise ValueError(
                'environment plane calibration is not approved; set '
                'calibration_valid: true only in a measured bundle')
        if (len(normal) != 3 or
                not all(isfinite(float(value)) for value in normal) or
                not isfinite(offset)):
            raise ValueError('plane equation must contain finite values')
        if sum(float(value) ** 2 for value in normal) ** 0.5 < 1.0e-12:
            raise ValueError('plane normal must be non-zero')
        if incidence <= 0.0 or incidence > 1.0:
            raise ValueError('minimum_incidence must be in (0, 1]')

        self._model = PinholeCameraModel()
        self._camera_frame = None
        self._image_width = 0
        self._image_height = 0
        self._uv_is_rectified = bool(
            self.get_parameter('uv_is_rectified').value)
        self._plane_normal = tuple(float(value) for value in normal)
        self._plane_offset = offset
        self._minimum_incidence = incidence
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        qos = rclpy.qos.qos_profile_sensor_data
        self.create_subscription(
            CameraInfo,
            self.get_parameter('camera_info_topic').value,
            self._on_camera_info,
            qos,
        )
        reliability = self.get_parameter('uv_qos_reliability').value
        if reliability == 'best_effort':
            uv_qos = rclpy.qos.qos_profile_sensor_data
        elif reliability == 'reliable':
            uv_qos = 10
        else:
            raise ValueError(
                'uv_qos_reliability must be best_effort or reliable')
        self.create_subscription(
            PointStamped,
            self.get_parameter('uv_topic').value,
            self._on_uv,
            uv_qos,
        )
        self._publisher = self.create_publisher(
            PointStamped, self.get_parameter('output_topic').value, 10)
        self.get_logger().info(
            f'Waiting for calibrated UV points on '
            f'{self.get_parameter("plane_name").value!r} plane '
            f'({("RECTIFIED" if self._uv_is_rectified else "RAW")} UV)')

    def _on_camera_info(self, message):
        coefficients = (*message.d, *message.k, *message.r, *message.p)
        focal_lengths = (
            message.k[0], message.k[4], message.p[0], message.p[5])
        if (not message.header.frame_id or message.width == 0 or message.height == 0 or
                not all(isfinite(value) for value in coefficients) or
                any(value == 0.0 for value in focal_lengths)):
            self.get_logger().error(
                'CameraInfo is uncalibrated or has invalid K/P focal lengths',
                throttle_duration_sec=5.0,
            )
            return
        self._model.from_camera_info(message)
        self._camera_frame = message.header.frame_id
        self._image_width = message.width
        self._image_height = message.height

    def _on_uv(self, message):
        if self._camera_frame is None:
            self.get_logger().warning('No CameraInfo received yet', throttle_duration_sec=2.0)
            return
        u, v = message.point.x, message.point.y
        if not isfinite(u) or not isfinite(v):
            self.get_logger().warning('UV contains a non-finite coordinate')
            return
        if message.header.frame_id and message.header.frame_id != self._camera_frame:
            self.get_logger().warning(
                f'UV frame {message.header.frame_id!r} does not match calibrated '
                f'camera frame {self._camera_frame!r}')
            return
        if not (0.0 <= u < self._image_width and 0.0 <= v < self._image_height):
            self.get_logger().warning(
                f'UV ({u:.1f}, {v:.1f}) is outside '
                f'{self._image_width}x{self._image_height}')
            return
        camera_frame = self._camera_frame
        stamp = Time.from_msg(message.header.stamp)
        if stamp.nanoseconds == 0:
            self.get_logger().warning('UV message has no acquisition timestamp')
            return
        target_frame = self.get_parameter('target_frame').value
        try:
            transform = self._tf_buffer.lookup_transform(target_frame, camera_frame, stamp)
            ray_camera = pixel_to_camera_ray(
                self._model, (u, v), self._uv_is_rectified)
            if not all(isfinite(float(value)) for value in ray_camera):
                raise ValueError('camera ray contains a non-finite value')
            q = transform.transform.rotation
            t = transform.transform.translation
            transform_values = (q.x, q.y, q.z, q.w, t.x, t.y, t.z)
            if not all(isfinite(value) for value in transform_values):
                raise ValueError('camera transform contains a non-finite value')
            ray_world = rotate_by_quaternion(ray_camera, (q.x, q.y, q.z, q.w))
            incidence = ray_plane_incidence(ray_world, self._plane_normal)
            if incidence < self._minimum_incidence:
                raise ValueError(
                    f'ray incidence {incidence:.4f} is below safety threshold')
            origin = (t.x, t.y, t.z)
            point = ray_plane_intersection(
                origin,
                ray_world,
                self._plane_normal,
                self._plane_offset,
            )
        except (TransformException, ValueError) as error:
            self.get_logger().warning(str(error), throttle_duration_sec=1.0)
            return

        output = PointStamped()
        output.header.stamp = message.header.stamp
        output.header.frame_id = target_frame
        output.point.x, output.point.y, output.point.z = point
        self._publisher.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = PlaneProjectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
