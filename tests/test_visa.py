import unittest

from ai.document_analysis.analyzer import build_document_record
from ai.document_analysis.document_classifier import classify_document
from ai.document_analysis.visa import analyze_visa


def visa_items():
    lines = [
        "REPUBLIC VISA",
        "Visa Number: V1234567",
        "Visa Type: TOURIST",
        "Number of Entries: MULTIPLE",
        "Valid From: 01/01/2026",
        "Valid Until: 31/12/2027",
        "Duration of Stay: 90 Days",
    ]
    return [
        {"text": text, "bbox": [[0, index * 10]]}
        for index, text in enumerate(lines)
    ]


class VisaAnalysisTests(unittest.TestCase):
    def test_classifies_visa(self):
        result = classify_document(visa_items())

        self.assertEqual(result["document_type"], "visa")
        self.assertGreaterEqual(result["confidence"], 0.75)

    def test_extracts_required_visa_fields(self):
        fields = analyze_visa(visa_items())["fields"]

        self.assertEqual(fields["visa_number"], "V1234567")
        self.assertEqual(fields["visa_type"], "TOURIST")
        self.assertEqual(fields["entries"], "MULTIPLE")
        self.assertEqual(fields["valid_until"], "2027-12-31")
        self.assertEqual(fields["stay_duration_days"], 90)

    def test_builds_valid_visa_document_record(self):
        result = build_document_record(visa_items())
        document = result["documents"][0]

        self.assertEqual(document["document_type"], "visa")
        self.assertFalse(document["mrz"]["required"])
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertEqual(document["risk"]["decision"], "PASS")

    def test_recognized_national_id_uses_generic_extraction_profile(self):
        result = build_document_record([
            {"text": "NATIONAL IDENTITY CARD", "bbox": [[0, 0]]},
            {"text": "Name: JANE ALICE DOE", "bbox": [[0, 10]]},
            {"text": "Identity Number: ID-998877", "bbox": [[0, 20]]},
            {"text": "Date of Birth: 01/01/1990", "bbox": [[0, 30]]},
        ])
        document = result["documents"][0]

        self.assertEqual(document["document_type"], "national_id")
        self.assertTrue(document["extraction"]["supported"])
        self.assertEqual(document["identity"]["name"], "JANE ALICE DOE")
        self.assertEqual(document["identity"]["document_number"], "ID-998877")
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertEqual(document["risk"]["decision"], "PASS")


if __name__ == "__main__":
    unittest.main()
