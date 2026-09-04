import unittest

from ai.document_analysis.risk_engine import calculate_risk


class RiskEngineTests(unittest.TestCase):
    def test_includes_cross_validation_mismatch(self):
        result = calculate_risk({
            "validation": {"issues": []},
            "mrz": {"detected": True},
            "cross_validation": {"mismatches": 2},
        })

        self.assertGreaterEqual(result["risk_score"], 40)
        self.assertIn(
            "FIELD_MISMATCH",
            [signal["signal"] for signal in result["signals"]],
        )

    def test_includes_high_forensic_score(self):
        result = calculate_risk({
            "validation": {"issues": []},
            "mrz": {"detected": True},
            "forensics": {
                "overall": {
                    "tampering_score": 72,
                    "signals": [{"signal": "ELA_ANOMALY"}],
                }
            },
        })

        self.assertEqual(result["decision"], "REVIEW")
        self.assertIn(
            "POSSIBLE_TAMPERING",
            [signal["signal"] for signal in result["signals"]],
        )

    def test_unverified_ocr_correction_requires_review_without_rejection(self):
        result = calculate_risk({
            "validation": {"issues": []},
            "document_type": "aadhaar",
            "mrz": {"required": False, "detected": False},
            "extraction": {
                "ocr_corrections": [{
                    "from": "6",
                    "to": "0",
                    "independently_verified": False,
                }],
            },
        })

        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["risk_score"], 25)
        self.assertIn(
            "OCR_CORRECTION_UNVERIFIED",
            [signal["signal"] for signal in result["signals"]],
        )

    def test_capture_failure_is_an_image_quality_signal(self):
        result = calculate_risk({
            "document_type": "national_id",
            "validation": {"issues": []},
            "mrz": {"required": False, "detected": False},
            "forensics": {"overall": {
                "tampering_score": 0,
                "capture_quality": {
                    "blocking": True,
                    "status": "RECAPTURE",
                    "signals": ["IMAGE_BLUR"],
                },
            }},
        })

        self.assertEqual(result["decision"], "REVIEW")
        quality_signal = next(
            signal for signal in result["signals"]
            if signal["signal"] == "CAPTURE_QUALITY_INSUFFICIENT"
        )
        self.assertEqual(quality_signal["type"], "IMAGE_QUALITY")
        self.assertNotIn(
            "POSSIBLE_TAMPERING",
            [signal["signal"] for signal in result["signals"]],
        )


if __name__ == "__main__":
    unittest.main()
