import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ai.image_forensics.geometry import analyze_geometry
from ai.verification_engine import combine_verification
from mock_data import passing_face_result


class CaptureQualityTests(unittest.TestCase):
    def test_flat_overexposed_capture_requests_recapture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "washed-out.png"
            cv2.imwrite(str(path), np.full((900, 1400, 3), 255, dtype=np.uint8))
            quality = analyze_geometry(path)["capture_quality"]

        self.assertTrue(quality["blocking"])
        self.assertEqual(quality["status"], "RECAPTURE")
        self.assertIn("POOR_IMAGE_EXPOSURE", quality["signals"])
        self.assertTrue(quality["guidance"])

    def test_quality_failure_is_separate_from_tampering(self):
        document_result = {
            "documents": [{
                "document_type": "national_id",
                "identity": {},
                "mrz": {"required": False, "detected": False},
                "expiry": {"status": "UNKNOWN"},
                "validation": {"validation_score": 100, "issues": []},
                "risk": {"risk_score": 0, "decision": "PASS"},
                "forensics": {"overall": {
                    "tampering_score": 0,
                    "capture_quality": {
                        "blocking": True,
                        "status": "RECAPTURE",
                        "signals": ["IMAGE_BLUR"],
                    },
                }},
            }],
        }

        decision = combine_verification(document_result, passing_face_result())

        self.assertEqual(decision["decision"], "RETRY")
        self.assertIn("IMAGE_RECAPTURE_REQUIRED", decision["reasons"])
        self.assertNotIn("POSSIBLE_TAMPERING", decision["reasons"])


if __name__ == "__main__":
    unittest.main()
