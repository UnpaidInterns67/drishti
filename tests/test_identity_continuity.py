import unittest

from ai.identity_continuity import build_continuity_assessment


class IdentityContinuityTests(unittest.TestCase):
    def test_escalates_same_face_with_conflicting_biographics(self):
        assessment = build_continuity_assessment(
            {
                "passport_number": "NEW456",
                "name": "BOB SMITH",
                "date_of_birth": "1985-05-05",
            },
            "passport",
            {
                "matches": [{
                    "identity_id": "traveller-1",
                    "document_number": "OLD123",
                    "similarity": 0.94,
                }],
                "duplicate_matches": [{
                    "identity_id": "traveller-1",
                    "document_number": "OLD123",
                    "similarity": 0.94,
                    "biographic_comparison": {
                        "conflicts": ["name", "date_of_birth"],
                    },
                }],
                "same_identity_matches": [],
            },
            [{
                "session_id": "previous-crossing",
                "checkpoint_code": "ICP-ATTARI-01",
                "movement": "ENTRY",
                "document_number": "OLD123",
                "decision": "APPROVE",
                "created_at": "2026-08-20T10:00:00+00:00",
            }],
        )

        self.assertEqual(assessment["status"], "IDENTITY_CONFLICT")
        self.assertEqual(
            assessment["conflicting_fields"],
            ["name", "date_of_birth"],
        )
        self.assertEqual(assessment["linked_document_count"], 2)
        self.assertEqual(
            assessment["alerts"][0]["code"],
            "SAME_FACE_DIFFERENT_IDENTITY",
        )
        graph = assessment["graph"]
        self.assertIn("biometric", {node["type"] for node in graph["nodes"]})
        self.assertIn("document", {node["type"] for node in graph["nodes"]})
        self.assertTrue(any(
            edge["state"] == "conflict" for edge in graph["edges"]
        ))

    def test_confirms_legitimate_new_document_history(self):
        assessment = build_continuity_assessment(
            {"passport_number": "NEW456", "name": "JANE DOE"},
            "passport",
            {
                "matches": [{
                    "identity_id": "traveller-1",
                    "document_number": "OLD123",
                }],
                "same_identity_matches": [{
                    "identity_id": "traveller-1",
                    "document_number": "OLD123",
                }],
                "duplicate_matches": [],
            },
            [{"document_number": "OLD123"}],
        )

        self.assertEqual(assessment["status"], "CONTINUITY_CONFIRMED")
        self.assertEqual(
            assessment["alerts"][0]["code"],
            "KNOWN_TRAVELLER_NEW_DOCUMENT",
        )


if __name__ == "__main__":
    unittest.main()
