import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.database import SQLiteDatabase


def screening_snapshot(session_id="screening-1"):
    return {
        "session_id": session_id,
        "created_at": "2026-08-29T10:00:00+00:00",
        "updated_at": "2026-08-29T10:00:00+00:00",
        "document": {
            "documents": [{
                "identity": {
                    "document_number": "A1234567",
                    "name": "Jane Alice Doe",
                    "date_of_birth": "1990-01-01",
                }
            }]
        },
        "face": None,
        "final": None,
        "face_session_active": False,
    }


class SQLiteDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "screenings.db"
        self.database = SQLiteDatabase(self.database_path)
        self.database.initialize()

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_screening_persists_across_repository_instances(self):
        snapshot = screening_snapshot()
        self.database.save_screening(snapshot)
        self.database.add_audit_event(
            snapshot["session_id"],
            "DOCUMENT_ANALYZED",
            {"document_type": "passport"},
        )

        reopened = SQLiteDatabase(self.database_path)
        stored = reopened.get_screening(snapshot["session_id"])
        events = reopened.get_audit_events(snapshot["session_id"])

        self.assertEqual(stored["status"], "DOCUMENT_ANALYZED")
        self.assertEqual(
            stored["document"]["documents"][0]["identity"]["document_number"],
            "A1234567",
        )
        self.assertEqual(events[0]["event_type"], "DOCUMENT_ANALYZED")

    def test_watchlist_match_is_normalized_and_can_be_deactivated(self):
        entry = self.database.create_watchlist_entry({
            "document_number": "A-123 4567",
            "full_name": "Jane Alice Doe",
            "date_of_birth": "1990-01-01",
            "nationality": "IND",
            "reason": "Synthetic test entry",
            "metadata": {"case": "TEST-1"},
        })

        result = self.database.check_watchlist({
            "document_number": "a1234567",
            "name": "JANE ALICE DOE",
            "date_of_birth": "1990-01-01",
        })
        self.assertTrue(result["match"])
        self.assertTrue(result["document_blacklisted"])
        self.assertEqual(result["metadata"]["matches"][0]["id"], entry["id"])

        self.assertTrue(self.database.deactivate_watchlist_entry(entry["id"]))
        self.assertFalse(self.database.check_watchlist({
            "document_number": "A1234567"
        })["match"])

    def test_purge_removes_screening_audit_and_enrolled_embedding(self):
        snapshot = screening_snapshot("screening-delete")
        self.database.save_screening(snapshot)
        self.database.add_audit_event(snapshot["session_id"], "DOCUMENT_ANALYZED")
        self.database.save_border_crossing({
            "session_id": snapshot["session_id"],
            "identity_id": snapshot["session_id"],
            "checkpoint_code": "ICP-ATTARI-01",
            "movement": "ENTRY",
            "document_type": "passport",
            "document_number": "A1234567",
            "full_name": "Jane Alice Doe",
            "date_of_birth": "1990-01-01",
            "nationality": "IND",
            "decision": "APPROVE",
            "risk_score": 0,
            "continuity_status": "NEW_TRAVELLER",
        })
        self.database.save_face_embedding(
            identity_id=snapshot["session_id"],
            document_number="A1234567",
            embedding=np.array([[0.1, 0.2, 0.3]], dtype=np.float32),
        )

        removed = self.database.purge_screening(snapshot["session_id"])

        self.assertEqual(removed["screenings"], 1)
        self.assertEqual(removed["audit_events"], 1)
        self.assertEqual(removed["face_embeddings"], 1)
        self.assertEqual(removed["border_crossings"], 1)
        self.assertIsNone(self.database.get_screening(snapshot["session_id"]))
        self.assertEqual(self.database.get_audit_events(snapshot["session_id"]), [])
        self.assertEqual(self.database.list_face_embeddings(), [])
        self.assertEqual(self.database.list_border_crossings(), [])

    def test_border_crossings_form_an_identity_timeline(self):
        for index, document_number in enumerate(("OLD123", "NEW456"), start=1):
            self.database.save_border_crossing({
                "session_id": f"crossing-{index}",
                "identity_id": "traveller-1",
                "checkpoint_code": f"ICP-{index}",
                "movement": "ENTRY" if index == 1 else "EXIT",
                "document_type": "passport",
                "document_number": document_number,
                "full_name": "Jane Doe",
                "date_of_birth": "1990-01-01",
                "nationality": "IND",
                "decision": "APPROVE",
                "risk_score": 0,
                "continuity_status": "CONTINUITY_CONFIRMED",
                "created_at": f"2026-08-{20 + index}T10:00:00+00:00",
            })

        timeline = self.database.list_border_crossings(
            identity_ids=["traveller-1"]
        )

        self.assertEqual([event["document_number"] for event in timeline], [
            "NEW456",
            "OLD123",
        ])
        self.assertEqual(timeline[0]["checkpoint_code"], "ICP-2")

    def test_face_embedding_round_trips_as_float32(self):
        vector = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        self.database.save_face_embedding(
            identity_id="identity-1",
            document_number="P-123 456",
            embedding=vector,
            full_name="JANE DOE",
            date_of_birth="1990-01-01",
        )

        reopened = SQLiteDatabase(self.database_path)
        records = reopened.list_face_embeddings()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["document_number"], "P-123 456")
        self.assertEqual(records[0]["full_name"], "JANE DOE")
        self.assertEqual(records[0]["date_of_birth"], "1990-01-01")
        np.testing.assert_allclose(records[0]["embedding"], vector.reshape(-1))

    def test_security_events_are_append_only_and_bounded(self):
        self.database.add_security_event(
            "LOGIN_FAILED",
            username="officer-one",
            source_ip="127.0.0.1",
            request_id="request-123",
            event_data={"reason": "INVALID_CREDENTIALS"},
        )

        events = self.database.list_security_events(limit=1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "LOGIN_FAILED")
        self.assertEqual(events[0]["username"], "officer-one")
        self.assertEqual(events[0]["data"]["reason"], "INVALID_CREDENTIALS")


if __name__ == "__main__":
    unittest.main()
