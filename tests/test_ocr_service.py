import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from backend.ocr_service import OCRService


class _RapidResult:
    boxes = np.array([[[0, 20], [100, 20], [100, 40], [0, 40]]], dtype=np.float32)
    txts = ("Government of India",)
    scores = (0.98,)


class _RapidReader:
    def __init__(self):
        self.image_shape = None
        self.options = None

    def __call__(self, image, **options):
        self.image_shape = image.shape
        self.options = options
        return _RapidResult()


class OCRServiceTests(unittest.TestCase):
    def test_uses_rapid_engine_and_downscales_large_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.png"
            cv2.imwrite(str(path), np.full((1200, 3200, 3), 255, dtype=np.uint8))
            service = OCRService()
            reader = _RapidReader()
            service._rapid_reader = reader

            result = service.extract(path)

        self.assertEqual(result[0]["text"], "Government of India")
        self.assertAlmostEqual(result[0]["confidence"], 0.98)
        self.assertEqual(max(reader.image_shape[:2]), 1280)
        self.assertEqual(reader.options, {"use_cls": False})


if __name__ == "__main__":
    unittest.main()
