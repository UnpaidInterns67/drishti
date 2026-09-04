import unittest

from ai.document_analysis.validation import (
    validate_dates,
    validate_document_number,
    validate_mrz,
)


class DocumentValidationTests(unittest.TestCase):
    def test_accepts_variable_length_passport_number(self):
        self.assertTrue(validate_document_number("Z9999999")["valid"])

    def test_does_not_reject_child_passport_holder(self):
        result = validate_dates({
            "date_of_birth": "2015-01-01",
            "date_of_expiry": "2030-01-01",
        })

        self.assertTrue(result["valid"])
        self.assertNotIn("UNUSUAL_DOCUMENT_AGE", result["issues"])

    def test_rejects_failed_mrz_checksums(self):
        result = validate_mrz({
            "detected": True,
            "checksums": {"valid": False},
        })

        self.assertFalse(result["valid"])
        self.assertIn("MRZ_CHECKSUM_FAILED", result["issues"])


if __name__ == "__main__":
    unittest.main()
