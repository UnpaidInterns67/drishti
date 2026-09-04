import re
import unittest

from ai.document_analysis.aadhaar import (
    analyze_aadhaar,
    correct_aadhaar_number,
    verhoeff_valid,
)
from ai.document_analysis.analyzer import build_document_record
from ai.document_analysis.document_classifier import classify_document
from ai.verification_engine import combine_verification


def _valid_aadhaar(prefix="23456789012"):
    return next(prefix + digit for digit in "0123456789" if verhoeff_valid(prefix + digit))


def aadhaar_items(masked=False):
    number = _valid_aadhaar()
    displayed = f"XXXX XXXX {number[-4:]}" if masked else f"{number[:4]} {number[4:8]} {number[8:]}"
    lines = [
        "Government of India",
        "RAHUL KUMAR SHARMA",
        "DOB: 24/05/1985",
        "Male",
        displayed,
        "Mera Aadhaar, Meri Pehchaan",
    ]
    return [{"text": text, "confidence": 0.99} for text in lines]


class AadhaarAnalysisTests(unittest.TestCase):
    def test_classifies_aadhaar(self):
        result = classify_document(aadhaar_items())

        self.assertEqual(result["document_type"], "aadhaar")

    def test_extracts_aadhaar_fields(self):
        result = analyze_aadhaar(aadhaar_items())
        fields = result["fields"]

        self.assertEqual(fields["name"], "RAHUL KUMAR SHARMA")
        self.assertEqual(fields["date_of_birth"], "1985-05-24")
        self.assertEqual(fields["sex"], "M")
        self.assertTrue(verhoeff_valid(fields["document_number"]))
        self.assertRegex(fields["document_number_masked"], r"^XXXX XXXX \d{4}$")

    def test_builds_valid_aadhaar_without_mrz_or_expiry(self):
        result = build_document_record(aadhaar_items())
        document = result["documents"][0]

        self.assertEqual(document["document_type"], "aadhaar")
        self.assertFalse(document["mrz"]["required"])
        self.assertEqual(document["expiry"]["status"], "NOT_APPLICABLE")
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertNotIn("MRZ_MISSING", document["risk"]["reasons"])
        self.assertNotIn("EXPIRY_MISSING", document["risk"]["reasons"])
        self.assertEqual(document["risk"]["decision"], "PASS")

    def test_accepts_masked_aadhaar_without_checksum_penalty(self):
        document = build_document_record(aadhaar_items(masked=True))["documents"][0]

        self.assertTrue(document["identity"]["aadhaar_masked"])
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertNotIn("INVALID_AADHAAR_CHECKSUM", document["validation"]["issues"])

    def test_valid_aadhaar_and_biometrics_can_be_approved(self):
        document = build_document_record(aadhaar_items())
        face = {
            "verification_passed": True,
            "face_match": True,
            "liveness_passed": True,
            "liveness_score": 1.0,
        }

        result = combine_verification(document, face)

        self.assertEqual(result["decision"], "APPROVE")
        self.assertTrue(result["verified"])

    def test_corrects_zero_misread_as_six_using_checksum(self):
        # 2000 0008 8000 is checksum-valid; model the reported OCR error where
        # the penultimate zero is read as six.
        corrected, corrections = correct_aadhaar_number("2000 0008 8060")

        self.assertEqual(corrected, "200000088000")
        self.assertEqual(corrections[0]["from"], "6")
        self.assertEqual(corrections[0]["to"], "0")
        self.assertEqual(corrections[0]["reason"], "AADHAAR_VERHOEFF_CHECKSUM")

    def test_record_uses_checksum_corrected_number(self):
        items = aadhaar_items()
        for item in items:
            if re.search(r"\d{4}\s+\d{4}\s+\d{4}", item["text"]):
                item["text"] = "2000 0008 8060"

        document = build_document_record(items)["documents"][0]

        self.assertEqual(document["identity"]["document_number_masked"], "XXXX XXXX 8000")
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertEqual(document["risk"]["decision"], "PASS")
        self.assertIn(
            "OCR_CORRECTION_UNVERIFIED",
            [signal["signal"] for signal in document["risk"]["signals"]],
        )
        self.assertEqual(
            document["extraction"]["ocr_corrections"][0]["reason"],
            "AADHAAR_VERHOEFF_CHECKSUM",
        )
        self.assertTrue(
            document["extraction"]["ocr_corrections"][0]["requires_manual_review"]
        )

    def test_corrected_aadhaar_cannot_be_auto_approved(self):
        items = aadhaar_items()
        for item in items:
            if re.search(r"\d{4}\s+\d{4}\s+\d{4}", item["text"]):
                item["text"] = "2000 0008 8060"
        face = {
            "verification_passed": True,
            "face_match": True,
            "liveness_passed": True,
        }

        result = combine_verification(build_document_record(items), face)

        self.assertEqual(result["decision"], "RETRY")
        self.assertTrue(result["retry_required"])
        self.assertIn("OCR_CORRECTION_REQUIRES_REVIEW", result["reasons"])


if __name__ == "__main__":
    unittest.main()
