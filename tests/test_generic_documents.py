import unittest

from ai.document_analysis.analyzer import build_document_record
from ai.document_analysis.generic_document import analyze_generic_document


def items(*lines):
    return [
        {"text": line, "bbox": [[0, index * 20]]}
        for index, line in enumerate(lines)
    ]


class GenericDocumentTests(unittest.TestCase):
    def test_extracts_driving_licence_fields_with_provenance(self):
        result = analyze_generic_document(items(
            "DRIVING LICENCE",
            "Name: ALEX MORGAN",
            "DL No: DL-04202400123",
            "Date of Birth: 14/09/1992",
            "Date of Issue: 01/04/2024",
            "Valid Until: 31/03/2034",
            "Vehicle Class: LMV, MCWG",
            "Blood Group: O+",
        ), "driving_license")

        self.assertEqual(result["fields"]["name"], "ALEX MORGAN")
        self.assertEqual(result["fields"]["document_number"], "DL-04202400123")
        self.assertEqual(result["fields"]["date_of_expiry"], "2034-03-31")
        self.assertEqual(result["fields"]["vehicle_classes"], ["LMV", "MCWG"])
        self.assertEqual(
            result["field_provenance"]["document_number"]["source"],
            "VISIBLE_ZONE_OCR",
        )

    def test_builds_valid_residence_permit(self):
        result = build_document_record(items(
            "RESIDENCE PERMIT",
            "Holder Name: PRIYA SHARMA",
            "Permit No: RP-2026-7788",
            "Permit Type: RESIDENCE",
            "Valid From: 01/01/2026",
            "Valid Until: 31/12/2028",
        ))
        document = result["documents"][0]

        self.assertEqual(document["document_type"], "permit")
        self.assertEqual(document["identity"]["permit_type"], "RESIDENCE")
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertEqual(document["risk"]["decision"], "PASS")

    def test_invalid_generic_validity_range_is_flagged(self):
        result = build_document_record(items(
            "WORK PERMIT",
            "Name: TEST PERSON",
            "Permit Number: WP-100",
            "Permit Type: WORK",
            "Valid From: 01/01/2030",
            "Valid Until: 01/01/2029",
        ))
        document = result["documents"][0]

        self.assertIn("INVALID_VALIDITY_RANGE", document["validation"]["issues"])
        self.assertEqual(document["risk"]["decision"], "REVIEW")

    def test_unknown_document_fails_closed(self):
        result = build_document_record(items("UNRECOGNIZED CREDENTIAL"))
        document = result["documents"][0]

        self.assertEqual(document["document_type"], "unknown")
        self.assertFalse(document["extraction"]["supported"])
        self.assertIn("UNSUPPORTED_DOCUMENT_TYPE", document["validation"]["issues"])


if __name__ == "__main__":
    unittest.main()
