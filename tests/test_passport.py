import unittest

from ai.document_analysis.analyzer import build_document_record
from ai.document_analysis.passport import analyze_passport


def item(text, x, y):
    return {
        "text": text,
        "bbox": [[x, y], [x + 100, y], [x + 100, y + 20], [x, y + 20]],
    }


def noisy_specimen_items():
    return [
        item("PASSPORT", 1200, 100),
        item("IND", 700, 145),
        item("KUMAR G", 550, 350),
        item("Date 0/ Bith", 670, 420),
        item("24/05/1985", 550, 460),
        item("M", 1000, 465),
        item("Date of Expiny", 1200, 740),
        item("01/01/2023", 1230, 790),
        item("Date of Issue", 550, 745),
        item("01/01/2013", 560, 790),
        item("P<<SPECIMEN<<KUMAR<G<<<<<<<<<<<<<<<<<<<<<<", 40, 935),
        item("29999999<01ND8505246M2300000<<<<<<<<<<<<<<<4", 40, 1015),
    ]


class PassportExtractionTests(unittest.TestCase):
    def test_associates_printed_dob_and_expiry_labels(self):
        fields = analyze_passport(noisy_specimen_items())["fields"]

        self.assertEqual(fields["date_of_birth"], "1985-05-24")
        self.assertEqual(fields["date_of_expiry"], "2023-01-01")

    def test_uses_visual_expiry_when_mrz_date_is_invalid(self):
        document = build_document_record(noisy_specimen_items())["documents"][0]

        self.assertTrue(document["mrz"]["detected"])
        self.assertEqual(document["identity"]["document_number"], "Z9999999")
        self.assertEqual(document["identity"]["date_of_birth"], "1985-05-24")
        self.assertEqual(document["identity"]["date_of_expiry"], "2023-01-01")
        self.assertIn("MRZ_CHECKSUM_FAILED", document["validation"]["issues"])
        self.assertIn("DOCUMENT_EXPIRED", document["validation"]["issues"])
        self.assertNotIn("MRZ_MISSING", document["validation"]["issues"])
        self.assertNotIn("DOB_MISSING", document["validation"]["issues"])
        self.assertNotIn("EXPIRY_MISSING", document["validation"]["issues"])

    def test_extracts_additional_visible_zone_fields(self):
        fields = analyze_passport([
            item("PASSPORT", 0, 0),
            item("Name: JANE ALICE DOE", 0, 20),
            item("Passport No: AB123456", 0, 40),
            item("Date of Issue: 02/01/2025", 0, 60),
            item("Place of Birth: DELHI", 0, 80),
            item("Place of Issue: MUMBAI", 0, 100),
            item("Issuing Authority: GOVT OF INDIA", 0, 120),
        ])["fields"]

        self.assertEqual(fields["name"], "JANE ALICE DOE")
        self.assertEqual(fields["document_number"], "AB123456")
        self.assertEqual(fields["date_of_issue"], "2025-01-02")
        self.assertEqual(fields["place_of_birth"], "DELHI")
        self.assertEqual(fields["place_of_issue"], "MUMBAI")
        self.assertEqual(fields["issuing_authority"], "GOVT OF INDIA")

    def test_visible_zone_mismatch_is_not_treated_as_missing_ocr(self):
        from mock_data import passport_ocr_items

        ocr = passport_ocr_items()
        for ocr_item in ocr:
            if ocr_item["text"].startswith("Passport No:"):
                ocr_item["text"] = "Passport No: B7654321"
        document = build_document_record(ocr)["documents"][0]

        comparison = document["cross_validation"]["fields"]["document_number"]
        self.assertEqual(comparison["status"], "MISMATCH")
        self.assertEqual(comparison["source"], "VISIBLE_ZONE_VS_MRZ")
        self.assertEqual(document["cross_validation"]["mismatches"], 1)
        self.assertEqual(document["risk"]["decision"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
