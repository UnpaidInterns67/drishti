import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ai.image_forensics.noise_analysis import analyze_noise


class NoiseAnalysisTests(unittest.TestCase):
    def _write(self, image):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "document.png"
        cv2.imwrite(str(path), image)
        return path

    def test_normal_document_layout_is_not_noise_tampering(self):
        image = np.full((600, 1000, 3), 235, dtype=np.uint8)
        cv2.rectangle(image, (40, 100), (270, 470), (170, 170, 170), -1)
        cv2.putText(image, "GOVERNMENT IDENTITY DOCUMENT", (320, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
        cv2.putText(image, "NAME  DATE OF BIRTH  1234 5678 9012", (320, 250),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 2)

        result = analyze_noise(self._write(image))

        self.assertFalse(result["suspicious"])
        self.assertEqual(result["method"], "FLAT_REGION_MEDIAN_RESIDUAL")

    def test_large_flat_region_noise_change_is_detected(self):
        rng = np.random.default_rng(7)
        image = np.full((600, 1000, 3), 180, dtype=np.uint8)
        patch = rng.normal(0, 28, (300, 500, 1))
        image[300:, 500:] = np.clip(image[300:, 500:] + patch, 0, 255)

        result = analyze_noise(self._write(image))

        self.assertTrue(result["suspicious"])


if __name__ == "__main__":
    unittest.main()
