import unittest
from unittest.mock import patch

from ai.face_verification.liveness import LivenessDetector


class BlinkDetectionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(LivenessDetector, "close")
        self.addCleanup(patcher.stop)
        patcher.start()
        self.detector = LivenessDetector.__new__(LivenessDetector)
        self.detector.reset()

    def test_calibrates_before_requesting_blink(self):
        self.detector._calibrate_blink(0.28)
        self.detector._calibrate_blink(0.29)

        self.assertFalse(self.detector.blink_ready)
        self.assertIn("keep your eyes open", self.detector.instruction().lower())

        self.detector._calibrate_blink(0.30)

        self.assertTrue(self.detector.blink_ready)
        self.assertEqual(self.detector.instruction(), "Blink once")
        self.assertAlmostEqual(self.detector.open_ear_baseline, 0.30)

    def test_accepts_one_closed_sample_followed_by_reopen(self):
        self.detector.blink_ready = True
        self.detector.open_ear_baseline = 0.30

        self.detector._process_blink(0.15)
        self.assertEqual(self.detector.closed_frames, 1)
        self.assertFalse(self.detector.blink_detected)

        self.detector._process_blink(0.29)

        self.assertTrue(self.detector.blink_detected)
        self.assertEqual(self.detector.state, "TURN_HEAD")

    def test_does_not_accept_closed_eyes_without_reopening(self):
        self.detector.blink_ready = True
        self.detector.open_ear_baseline = 0.30

        self.detector._process_blink(0.15)
        self.detector._process_blink(0.18)

        self.assertFalse(self.detector.blink_detected)
        self.assertEqual(self.detector.state, "BLINK")

    def test_adapts_to_lower_open_eye_ratio(self):
        self.detector.blink_ready = True
        self.detector.open_ear_baseline = 0.22

        self.detector._process_blink(0.13)
        self.detector._process_blink(0.21)

        self.assertTrue(self.detector.blink_detected)


if __name__ == "__main__":
    unittest.main()
