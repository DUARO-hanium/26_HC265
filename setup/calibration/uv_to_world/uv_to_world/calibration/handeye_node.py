from math import degrees
import os
import time

import cv2
from cv_bridge import CvBridge
import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
import yaml

from .handeye_math import (
    calibration_residuals,
    matrix_to_quaternion,
    rotation_angle,
    solve_eye_to_hand,
)


def transform_message_to_matrix(message):
    t = message.transform.translation
    q = message.transform.rotation
    x, y, z, w = q.x, q.y, q.z, q.w
    length = np.linalg.norm([x, y, z, w])
    x, y, z, w = np.array([x, y, z, w]) / length
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    result = np.eye(4)
    result[:3, :3] = rotation
    result[:3, 3] = [t.x, t.y, t.z]
    return result


class HandEyeCalibrator(Node):
    def __init__(self):
        super().__init__('handeye_calibrator')
        parameters = {
            'image_topic': '/camera1/image_raw',
            'camera_info_topic': '/camera1/camera_info',
            'debug_image_topic': '/camera1/handeye/debug_image',
            'base_frame': 'link0',
            'tool_frame': 'end_effector_link',
            'camera_frame': 'camera1_optical_frame',
            'squares_x': 7,
            'squares_y': 5,
            'square_length': 0.024,
            'marker_length': 0.01728,
            'dictionary': 'DICT_5X5_100',
            'minimum_corners': 8,
            'minimum_samples': 15,
            'max_reprojection_error_px': 1.0,
            'minimum_translation_change_m': 0.015,
            'minimum_rotation_change_deg': 8.0,
            'max_sample_age_sec': 1.0,
            # Allow the slower robot TF stream to catch up to the image timestamp.
            'tf_lookup_timeout_sec': 0.2,
            # Windows camera timestamps can lead the ~15 Hz robot TF stream by
            # one update.  Only accept a latest-TF fallback when it is this
            # close to the image; calibration samples must be taken at rest.
            'max_tf_image_skew_sec': 0.1,
            'max_translation_rms_m': 0.005,
            'max_rotation_rms_deg': 1.0,
            'output_file': '~/.ros/uv_to_world/eye_to_hand.yaml',
        }
        for name, value in parameters.items():
            self.declare_parameter(name, value)

        self._bridge = CvBridge()
        self._camera_matrix = None
        self._distortion = None
        self._latest = None
        self._base_to_tool = []
        self._camera_to_target = []
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._create_board()

        qos = rclpy.qos.qos_profile_sensor_data
        self._debug_publisher = self.create_publisher(
            Image, self._p('debug_image_topic'), qos)
        self.create_subscription(CameraInfo, self._p('camera_info_topic'),
                                 self._on_camera_info, qos)
        self.create_subscription(Image, self._p('image_topic'), self._on_image, qos)
        self.create_service(Trigger, '~/capture', self._capture)
        self.create_service(Trigger, '~/solve', self._solve)
        self.create_service(Trigger, '~/reset', self._reset)
        self.get_logger().info(
            'ChArUco eye-to-hand calibrator ready; waiting for image and CameraInfo')

    def _p(self, name):
        return self.get_parameter(name).value

    def _create_board(self):
        dictionary_name = self._p('dictionary')
        if not hasattr(cv2.aruco, dictionary_name):
            raise ValueError(f'unknown ArUco dictionary: {dictionary_name}')
        dictionary_id = getattr(cv2.aruco, dictionary_name)
        self._dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        self._board = cv2.aruco.CharucoBoard_create(
            self._p('squares_x'), self._p('squares_y'),
            self._p('square_length'), self._p('marker_length'), self._dictionary)
        self._detector_parameters = cv2.aruco.DetectorParameters_create()

    def _on_camera_info(self, message):
        if message.k[0] == 0.0:
            self.get_logger().error('CameraInfo is uncalibrated', throttle_duration_sec=5.0)
            return
        if message.header.frame_id != self._p('camera_frame'):
            self.get_logger().error(
                f'CameraInfo frame {message.header.frame_id!r} does not match '
                f'camera_frame {self._p("camera_frame")!r}',
                throttle_duration_sec=5.0)
            return
        self._camera_matrix = np.asarray(message.k, dtype=np.float64).reshape(3, 3)
        self._distortion = np.asarray(message.d, dtype=np.float64)

    def _on_image(self, message):
        image = self._bridge.imgmsg_to_cv2(message, desired_encoding='bgr8')
        debug_image = image.copy()
        if self._camera_matrix is None:
            self._publish_debug(
                debug_image, message.header, 'WAITING FOR CAMERA_INFO', (0, 165, 255))
            return
        corners, ids, _ = cv2.aruco.detectMarkers(
            image, self._dictionary, parameters=self._detector_parameters)
        if ids is None:
            self._latest = None
            self._publish_debug(
                debug_image, message.header, 'NO ARUCO MARKERS', (0, 0, 255))
            return
        cv2.aruco.drawDetectedMarkers(debug_image, corners, ids)
        count, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            corners, ids, image, self._board, self._camera_matrix, self._distortion)
        if count is None or count < self._p('minimum_corners'):
            self._latest = None
            detected = 0 if count is None else int(count)
            self._publish_debug(
                debug_image, message.header,
                f'INSUFFICIENT CORNERS: {detected}/{self._p("minimum_corners")}',
                (0, 0, 255))
            return
        cv2.aruco.drawDetectedCornersCharuco(
            debug_image, charuco_corners, charuco_ids, (0, 255, 0))
        valid, rvec, tvec = cv2.aruco.estimatePoseCharucoBoard(
            charuco_corners, charuco_ids, self._board,
            self._camera_matrix, self._distortion, None, None)
        if not valid:
            self._latest = None
            self._publish_debug(
                debug_image, message.header, 'POSE ESTIMATION FAILED', (0, 0, 255))
            return

        object_points = self._board.chessboardCorners[
            charuco_ids.flatten()].reshape(-1, 3)
        projected, _ = cv2.projectPoints(
            object_points, rvec, tvec, self._camera_matrix, self._distortion)
        observed = charuco_corners.reshape(-1, 2)
        reprojection_error = float(np.sqrt(np.mean(np.sum(
            (projected.reshape(-1, 2) - observed) ** 2, axis=1))))
        cv2.drawFrameAxes(
            debug_image, self._camera_matrix, self._distortion,
            rvec, tvec, self._p('square_length') * 2.0)

        camera_to_target = np.eye(4)
        camera_to_target[:3, :3] = cv2.Rodrigues(rvec)[0]
        camera_to_target[:3, 3] = tvec.reshape(3)
        image_stamp = Time.from_msg(message.header.stamp)
        tf_skew_sec = 0.0
        try:
            transform = self._tf_buffer.lookup_transform(
                self._p('base_frame'), self._p('tool_frame'), image_stamp,
                timeout=Duration(seconds=self._p('tf_lookup_timeout_sec')))
        except TransformException as error:
            try:
                transform = self._tf_buffer.lookup_transform(
                    self._p('base_frame'), self._p('tool_frame'), Time())
                transform_stamp = Time.from_msg(transform.header.stamp)
                tf_skew_sec = abs(
                    image_stamp.nanoseconds - transform_stamp.nanoseconds) / 1e9
                max_skew = self._p('max_tf_image_skew_sec')
                if tf_skew_sec > max_skew:
                    raise TransformException(
                        f'latest robot TF differs from image by '
                        f'{tf_skew_sec:.3f}s (limit {max_skew:.3f}s)')
                self.get_logger().warning(
                    f'Using latest robot TF ({tf_skew_sec * 1000.0:.1f}ms '
                    f'from image); keep robot stationary before capture',
                    throttle_duration_sec=5.0)
            except TransformException as fallback_error:
                self.get_logger().warning(
                    f'{error}; fallback failed: {fallback_error}',
                    throttle_duration_sec=2.0)
                self._latest = None
                self._publish_debug(
                    debug_image, message.header,
                    f'TF UNAVAILABLE | {int(count)} corners | '
                    f'{reprojection_error:.3f}px',
                    (0, 165, 255))
                return
        self._latest = {
            'received': time.monotonic(),
            'base_to_tool': transform_message_to_matrix(transform),
            'camera_to_target': camera_to_target,
            'corners': int(count),
            'reprojection_error': reprojection_error,
            'tf_skew_sec': tf_skew_sec,
        }
        color = ((0, 255, 0) if
                 reprojection_error <= self._p('max_reprojection_error_px')
                 else (0, 0, 255))
        state = ('CAPTURE READY' if color == (0, 255, 0)
                 else 'REPROJECTION ERROR TOO HIGH')
        self._publish_debug(
            debug_image, message.header,
            f'{state} | {int(count)} corners | {reprojection_error:.3f}px',
            color)

    def _publish_debug(self, image, header, text, color):
        cv2.rectangle(image, (0, 0), (image.shape[1], 42), (0, 0, 0), -1)
        cv2.putText(
            image, text, (12, 29), cv2.FONT_HERSHEY_SIMPLEX,
            0.72, color, 2, cv2.LINE_AA)
        debug_message = self._bridge.cv2_to_imgmsg(image, encoding='bgr8')
        debug_message.header = header
        self._debug_publisher.publish(debug_message)

    def _capture(self, _request, response):
        if self._latest is None:
            response.message = 'No valid ChArUco pose and synchronized robot TF available'
            return response
        if time.monotonic() - self._latest['received'] > self._p('max_sample_age_sec'):
            response.message = 'Latest detection is stale; keep the board visible and retry'
            return response
        error = self._latest['reprojection_error']
        if error > self._p('max_reprojection_error_px'):
            response.message = f'Reprojection error {error:.3f}px exceeds threshold'
            return response
        robot = self._latest['base_to_tool']
        if self._base_to_tool:
            previous = self._base_to_tool[-1]
            translation = np.linalg.norm(robot[:3, 3] - previous[:3, 3])
            rotation = degrees(rotation_angle(previous[:3, :3].T @ robot[:3, :3]))
            if (translation < self._p('minimum_translation_change_m') and
                    rotation < self._p('minimum_rotation_change_deg')):
                response.message = (
                    f'Pose too similar: move {translation:.3f}m, rotate {rotation:.1f}deg')
                return response
        self._base_to_tool.append(robot.copy())
        self._camera_to_target.append(self._latest['camera_to_target'].copy())
        response.success = True
        response.message = (
            f'Sample {len(self._base_to_tool)} captured; '
            f'{self._latest["corners"]} corners, {error:.3f}px reprojection error, '
            f'{self._latest["tf_skew_sec"] * 1000.0:.1f}ms TF skew')
        return response

    def _solve(self, _request, response):
        minimum = self._p('minimum_samples')
        if len(self._base_to_tool) < minimum:
            response.message = f'Need at least {minimum} samples; have {len(self._base_to_tool)}'
            return response
        try:
            result, condition_residual = solve_eye_to_hand(
                self._base_to_tool, self._camera_to_target)
            translation_errors, rotation_errors = calibration_residuals(
                self._base_to_tool, self._camera_to_target, result)
        except (ValueError, np.linalg.LinAlgError) as error:
            response.message = str(error)
            return response

        translation_rms = float(np.sqrt(np.mean(translation_errors ** 2)))
        rotation_rms = degrees(float(np.sqrt(np.mean(rotation_errors ** 2))))
        valid = (translation_rms <= self._p('max_translation_rms_m') and
                 rotation_rms <= self._p('max_rotation_rms_deg'))
        quaternion = matrix_to_quaternion(result[:3, :3])
        output = os.path.expanduser(self._p('output_file'))
        os.makedirs(os.path.dirname(output), exist_ok=True)
        document = {
            'calibration': {
                'parent_frame': self._p('base_frame'),
                'child_frame': self._p('camera_frame'),
                'translation': [float(value) for value in result[:3, 3]],
                'quaternion_xyzw': [float(value) for value in quaternion],
                'sample_count': len(self._base_to_tool),
                'translation_rms_m': translation_rms,
                'rotation_rms_deg': rotation_rms,
                'solver_smallest_singular_value': condition_residual,
                'quality_passed': valid,
            }
        }
        with open(output, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(document, stream, sort_keys=False)
        response.success = valid
        response.message = (
            f'Saved {output}; RMS={translation_rms * 1000:.2f}mm, '
            f'{rotation_rms:.3f}deg, quality={"PASS" if valid else "FAIL"}')
        return response

    def _reset(self, _request, response):
        self._base_to_tool.clear()
        self._camera_to_target.clear()
        response.success = True
        response.message = 'All calibration samples cleared'
        return response


def main(args=None):
    rclpy.init(args=args)
    node = HandEyeCalibrator()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
