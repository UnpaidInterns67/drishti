import unittest

from ai.document_analysis.icao import (
    calculate_check_digit,
    correct_document_field,
    validate_td3_line2,
)


class IcaoCheckDigitTests(unittest.TestCase):
    def test_calculates_official_example_check_digit(self):
        self.assertEqual(calculate_check_digit("L898902C3"), "6")

    def test_validates_complete_td3_line(self):
        result = validate_td3_line2(
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
        )

        self.assertTrue(result["valid"])
        self.assertTrue(
            all(check["valid"] for check in result["checks"].values())
        )

    def test_rejects_modified_td3_data(self):
        result = validate_td3_line2(
            "L898902C36UTO7508122F1204159ZE184226B<<<<<10"
        )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["date_of_birth"]["valid"])

    def test_applies_unique_checksum_supported_ocr_correction(self):
        field, corrections = correct_document_field(
            "29999999<0IND8505246M2300000<<<<<<<<<<<<<<<4"
        )

        self.assertEqual(field, "Z9999999<")
        self.assertEqual(corrections[0]["reason"], "ICAO_CHECK_DIGIT")


if __name__ == "__main__":
    unittest.main()
