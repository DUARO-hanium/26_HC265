import unittest
import struct

import numpy as np

from live_inspection import (
    Detection,
    HeuristicStainDetector,
    TemporalDetectionGate,
    UdpFrameAssembler,
    configured_defect_classes,
    inference_views,
    normalized_roi,
    parse_source,
    suppress_duplicate_detections,
)


class ConfigurationTests(unittest.TestCase):
    def test_numeric_camera_source(self):
        self.assertEqual(parse_source(" 1 "), 1)

    def test_empty_camera_source_is_disabled(self):
        self.assertIsNone(parse_source("  "))

    def test_url_camera_source(self):
        url = "rtsp://camera.local/stream"
        self.assertEqual(parse_source(url), url)

    def test_defect_class_allow_list(self):
        self.assertEqual(configured_defect_classes("Stain, tear"), {"stain", "tear"})

    def test_wildcard_accepts_all_classes(self):
        self.assertIsNone(configured_defect_classes("*"))

    def test_normalized_roi(self):
        self.assertEqual(normalized_roi("0, 0.1, 1, 0.9"), (0.0, 0.1, 1.0, 0.9))

    def test_invalid_normalized_roi(self):
        with self.assertRaises(ValueError):
            normalized_roi("0.5,0,0.2,1")


class UdpFrameAssemblerTests(unittest.TestCase):
    def _packet(self, frame_id, index, count, jpeg, payload):
        header = struct.pack("!4sBBHHII", b"DCAM", 1, 18, index, count, frame_id, len(jpeg))
        return header + payload

    def test_reassembles_out_of_order_chunks(self):
        assembler = UdpFrameAssembler()
        sender = ("172.20.10.2", 1234)
        jpeg = b"\xff\xd8abcdef\xff\xd9"
        packets = [
            self._packet(7, 0, 3, jpeg, jpeg[:4]),
            self._packet(7, 1, 3, jpeg, jpeg[4:8]),
            self._packet(7, 2, 3, jpeg, jpeg[8:]),
        ]
        self.assertIsNone(assembler.push(packets[2], sender, 0.0))
        self.assertIsNone(assembler.push(packets[0], sender, 0.1))
        self.assertEqual(assembler.push(packets[1], sender, 0.2), jpeg)

    def test_accepts_legacy_single_jpeg_datagram(self):
        assembler = UdpFrameAssembler()
        jpeg = b"\xff\xd8legacy\xff\xd9"
        self.assertEqual(assembler.push(jpeg, ("127.0.0.1", 1)), jpeg)

    def test_discards_stale_incomplete_frame(self):
        assembler = UdpFrameAssembler()
        sender = ("172.20.10.2", 1234)
        jpeg = b"\xff\xd8abcdef\xff\xd9"
        assembler.push(self._packet(1, 0, 2, jpeg, jpeg[:5]), sender, 0.0)
        assembler.push(self._packet(2, 0, 2, jpeg, jpeg[:5]), sender, 2.0)
        self.assertNotIn((sender, 1), assembler._frames)


class TiledInferenceTests(unittest.TestCase):
    def test_full_frame_and_four_overlapping_crops_are_returned(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        views = inference_views(frame, rows=2, columns=2, overlap=0.2)
        self.assertEqual(len(views), 5)
        self.assertEqual(views[0][0].shape, frame.shape)
        self.assertEqual(views[0][1], (0, 0))
        self.assertTrue(all(view.size > 0 for view, _ in views))

    def test_duplicate_boxes_from_crop_and_full_frame_are_suppressed(self):
        detections = [
            Detection("stain", 0.70, (10, 10, 50, 50)),
            Detection("stain", 0.91, (11, 11, 51, 51)),
            Detection("tear", 0.80, (11, 11, 51, 51)),
        ]
        kept = suppress_duplicate_detections(detections, iou_threshold=0.5)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].confidence, 0.91)
        self.assertEqual({item.label for item in kept}, {"stain", "tear"})


class HeuristicDetectorTests(unittest.TestCase):
    def test_detects_red_patch_on_gray_garment(self):
        background = np.full((240, 320, 3), 80, dtype=np.uint8)
        frame = background.copy()
        frame[30:210, 40:280] = 150
        frame[80:120, 160:210] = (20, 20, 180)
        detector = HeuristicStainDetector(min_area=100, roi=(0, 0, 1, 1))
        detector.set_background(background)
        detections, annotated, latency = detector.predict(frame)
        self.assertTrue(detector.ready)
        self.assertGreaterEqual(len(detections), 1)
        self.assertEqual(detections[0].label, "stain_candidate")
        self.assertEqual(annotated.shape, frame.shape)
        self.assertGreaterEqual(latency, 0.0)

    def test_ignores_plain_gray_frame(self):
        frame = np.full((240, 320, 3), 150, dtype=np.uint8)
        detector = HeuristicStainDetector(roi=(0, 0, 1, 1))
        detector.set_background(frame)
        detections, _, _ = detector.predict(frame)
        self.assertEqual(detections, [])

    def test_ignores_bright_neutral_patch_with_high_raw_red(self):
        background = np.full((240, 320, 3), 80, dtype=np.uint8)
        frame = background.copy()
        frame[30:210, 40:280] = 150
        frame[80:120, 160:210] = (225, 225, 225)
        detector = HeuristicStainDetector(roi=(0, 0, 1, 1))
        detector.set_background(background)
        detections, _, _ = detector.predict(frame)
        self.assertEqual(detections, [])

    def test_keeps_only_the_strongest_red_candidate_by_default(self):
        background = np.full((240, 320, 3), 80, dtype=np.uint8)
        frame = background.copy()
        frame[30:210, 40:280] = 150
        frame[60:90, 70:110] = (30, 30, 180)
        frame[130:180, 190:250] = (20, 20, 210)
        detector = HeuristicStainDetector(min_area=100, roi=(0, 0, 1, 1))
        detector.set_background(background)
        detections, _, _ = detector.predict(frame)
        self.assertEqual(len(detections), 1)

    def test_ignores_red_object_unchanged_in_registered_background(self):
        background = np.full((240, 320, 3), 80, dtype=np.uint8)
        background[40:100, 130:180] = (20, 20, 190)
        detector = HeuristicStainDetector(roi=(0, 0, 1, 1))
        detector.set_background(background)
        detections, _, _ = detector.predict(background.copy())
        self.assertEqual(detections, [])


class TemporalDetectionGateTests(unittest.TestCase):
    def test_requires_three_consistent_frames(self):
        gate = TemporalDetectionGate(confirm_frames=3, release_frames=2)
        first = Detection("stain_candidate", 0.5, (10, 10, 40, 40))
        second = Detection("stain_candidate", 0.6, (11, 10, 41, 40))
        third = Detection("stain_candidate", 0.7, (10, 11, 40, 41))
        self.assertEqual(gate.update([first]), [])
        self.assertEqual(gate.update([second]), [])
        self.assertEqual(gate.update([third]), [third])

    def test_moving_noise_does_not_confirm(self):
        gate = TemporalDetectionGate(confirm_frames=3)
        boxes = [
            Detection("stain_candidate", 0.6, (10, 10, 30, 30)),
            Detection("stain_candidate", 0.6, (100, 100, 120, 120)),
            Detection("stain_candidate", 0.6, (200, 150, 220, 170)),
        ]
        self.assertTrue(all(gate.update([box]) == [] for box in boxes))


if __name__ == "__main__":
    unittest.main()
