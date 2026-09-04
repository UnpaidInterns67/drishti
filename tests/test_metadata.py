import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ai.image_forensics.metadata import analyze_metadata
from ai.image_forensics.forensic_engine import analyze_image_forensics


class MetadataAnalysisTests(unittest.TestCase):
    def test_detects_extension_format_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.jpg"
            Image.new("RGB", (10, 10), "white").save(path, format="PNG")

            result = analyze_metadata(path)

        self.assertTrue(result["extension_mismatch"])
        self.assertIn("FILE_EXTENSION_FORMAT_MISMATCH", result["signals"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_detects_editor_software_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.jpg"
            exif = Image.Exif()
            exif[305] = "Adobe Photoshop"
            Image.new("RGB", (10, 10), "white").save(path, exif=exif)

            result = analyze_metadata(path)

        self.assertEqual(result["editor_marker"], "adobe")
        self.assertIn("EDITING_SOFTWARE_METADATA", result["signals"])

    def test_editor_metadata_cannot_be_diluted_below_review_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.jpg"
            exif = Image.Exif()
            exif[305] = "Adobe Photoshop"
            Image.new("RGB", (400, 250), "white").save(path, exif=exif)

            result = analyze_image_forensics(path)

        self.assertGreaterEqual(result["overall"]["tampering_score"], 35)
        self.assertIn(
            "EDITING_SOFTWARE_METADATA",
            [signal["signal"] for signal in result["overall"]["signals"]],
        )
        self.assertTrue(result["limitations"])

    def test_weak_ela_region_does_not_alone_force_tampering_review(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.jpg"
            Image.new("RGB", (400, 250), "white").save(path)
            with patch(
                "ai.image_forensics.forensic_engine.perform_ela",
                return_value={
                    "ela_score": 2.0,
                    "suspicious": True,
                    "suspicious_regions": [{"bbox": [0, 0, 10, 10]}],
                },
            ):
                result = analyze_image_forensics(path)

        self.assertLess(result["overall"]["tampering_score"], 35)
        self.assertIn(
            "ELA_ANOMALY",
            [signal["signal"] for signal in result["overall"]["signals"]],
        )


if __name__ == "__main__":
    unittest.main()
