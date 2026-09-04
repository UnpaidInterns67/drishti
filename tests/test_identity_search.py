import unittest

import numpy as np

from ai.face_verification.identity_search import find_duplicate_identities


class IdentitySearchTests(unittest.TestCase):
    def test_flags_same_face_with_conflicting_identity(self):
        result = find_duplicate_identities(
            np.array([1.0, 0.0, 0.0]),
            [
                {
                    "identity_id": "person-1",
                    "document_number": "OLD123",
                    "full_name": "ALICE DOE",
                    "date_of_birth": "1990-01-01",
                    "embedding": [0.99, 0.01, 0.0],
                }
            ],
            document_number="NEW456",
            full_name="BOB SMITH",
            date_of_birth="1985-05-05",
            threshold=0.8,
        )

        self.assertTrue(result["duplicate_identity"])
        self.assertTrue(result["matches"][0]["different_document"])
        self.assertTrue(result["matches"][0]["identity_conflict"])

    def test_same_person_can_hold_different_documents(self):
        result = find_duplicate_identities(
            [1.0, 0.0],
            [{
                "identity_id": "person-1",
                "document_number": "P1234567",
                "full_name": "JANE ALICE DOE",
                "date_of_birth": "2006-11-30",
                "embedding": [1.0, 0.0],
            }],
            document_number="123456788000",
            full_name="Jane Alice Doe",
            date_of_birth="2006-11-30",
        )

        self.assertFalse(result["duplicate_identity"])
        self.assertTrue(result["matches"][0]["same_identity"])
        self.assertEqual(
            result["matches"][0]["document_relationship"],
            "DIFFERENT_DOCUMENT",
        )

    def test_masked_aadhaar_suffix_matches_existing_full_identifier(self):
        result = find_duplicate_identities(
            [1.0, 0.0],
            [{
                "identity_id": "person-1",
                "document_number": "123456788000",
                "full_name": "JANE ALICE DOE",
                "date_of_birth": "2006-11-30",
                "embedding": [1.0, 0.0],
            }],
            document_number="8000",
            full_name="JANE ALICE DOE",
            date_of_birth="2006-11-30",
        )

        self.assertFalse(result["duplicate_identity"])
        self.assertEqual(
            result["matches"][0]["document_relationship"],
            "MASKED_IDENTIFIER_MATCH",
        )

    def test_does_not_flag_same_document(self):
        result = find_duplicate_identities(
            [1.0, 0.0],
            [{"document_number": "P123", "embedding": [1.0, 0.0]}],
            document_number="P123",
        )

        self.assertFalse(result["duplicate_identity"])

    def test_normalizes_same_document_before_comparison(self):
        result = find_duplicate_identities(
            [1.0, 0.0],
            [{"document_number": "P-123 456", "embedding": [1.0, 0.0]}],
            document_number="p123456",
        )

        self.assertFalse(result["duplicate_identity"])


if __name__ == "__main__":
    unittest.main()
