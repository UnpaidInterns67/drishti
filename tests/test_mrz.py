import unittest

from ai.document_analysis.mrz import analyze_mrz


def ocr_item(text, y):
    return {"text": text, "bbox": [[0, y], [1, y], [1, y + 1], [0, y + 1]]}


class AnalyzeMrzTests(unittest.TestCase):
    def test_validates_standard_td3_checksums(self):
        items = [
            ocr_item("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", 10),
            ocr_item("L898902C36UTO7408122F1204159ZE184226B<<<<<10", 20),
        ]

        result = analyze_mrz(items)

        self.assertTrue(result["records"][0]["checksums"]["valid"])
        self.assertEqual(result["records"][0]["document_number"], "L898902C3")
        self.assertEqual(result["records"][0]["name"], "ANNA MARIA ERIKSSON")
        self.assertEqual(result["records"][0]["issuing_state"], "UTO")

    def test_prefers_standard_td3_record(self):
        items = [
            ocr_item("A12345678IND01011990M01012030", 10),
            ocr_item("P<SPECIMEN<<KUMAR<G<<<<<<<<<<<<<<<<<<<<<<<<", 20),
            ocr_item("29999999<0IND8505246M2300000<<<<<<<<<<<<<<<4", 30),
        ]

        result = analyze_mrz(items)

        self.assertTrue(result["mrz_detected"])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["document_number"], "Z9999999")

    def test_recovers_digit_confusion_in_nationality_position(self):
        items = [
            ocr_item("P<<SPECIMEN<<KUMAR<G<<<<<<<<<<<<<<<<<<<<<<", 10),
            ocr_item("29999999<01ND8505246M2300000<<<<<<<<<<<<<<<4", 20),
        ]

        result = analyze_mrz(items)

        self.assertTrue(result["mrz_detected"])
        record = result["records"][0]
        self.assertEqual(record["document_number"], "Z9999999")
        self.assertEqual(record["nationality"], "IND")
        self.assertEqual(record["name"], "KUMAR G")
        self.assertEqual(record["date_of_birth"], "1985-05-24")
        self.assertIsNone(record["date_of_expiry"])
        self.assertIn("nationality", {item["field"] for item in record["ocr_corrections"]})

    def test_uses_one_synthetic_fallback_record(self):
        items = [
            ocr_item("A12345678IND01011990M01012030", 10),
            ocr_item("B12345678IND02021991F02022031", 20),
        ]

        result = analyze_mrz(items)

        self.assertTrue(result["mrz_detected"])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["document_number"], "B12345678")

    def test_returns_no_records_when_mrz_is_missing(self):
        result = analyze_mrz([ocr_item("REPUBLIC OF INDIA", 10)])

        self.assertFalse(result["mrz_detected"])
        self.assertEqual(result["records"], [])


if __name__ == "__main__":
    unittest.main()
