import unittest
from contextlib import contextmanager
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.auth import auth_service
from backend.main import app
from mock_data import build_td3_line2, passport_ocr_items
from backend.main import database


class FakeVerifier:
    def __init__(self):
        self.session_active = False
        self.id_embedding = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)

    def start_session(self, _document_path):
        self.session_active = True
        return {"started": True, "state": "BLINK", "instruction": "Blink once"}

    def process_frame(self, _frame):
        self.session_active = False
        return {
            "verification_passed": True,
            "face_match": True,
            "face_similarity": 0.61,
            "liveness_passed": True,
            "liveness_score": 1.0,
        }

    def close_session(self):
        self.session_active = False


def mock_png():
    image = np.full((700, 1400, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Could not create mock PNG")
    return encoded.tobytes()


class FastApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        auth_service.create_officer_for_test(
            "integration-officer",
            "integration-password-123",
        )

    def tearDown(self):
        pass

    @contextmanager
    def authenticated_client(self):
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "integration-officer",
                    "password": "integration-password-123",
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            client.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})
            yield client

    def test_health_and_cors(self):
        with TestClient(app) as client:
            health = client.get("/health")
            preflight = client.options(
                "/api/v1/screenings",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )

    def test_officer_auth_protects_active_checkpoint(self):
        with TestClient(app, base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
            denied = client.post(
                "/api/v1/auth/login",
                json={"username": "integration-officer", "password": "wrong"},
            )
            self.assertEqual(denied.status_code, 401)

            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "integration-officer",
                    "password": "integration-password-123",
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            cookie = login.headers["set-cookie"].lower()
            self.assertIn("httponly", cookie)
            self.assertIn("secure", cookie)
            self.assertIn("samesite=strict", cookie)

            switch_path = "/api/v1/auth/active-checkpoint"
            without_csrf = client.post(
                switch_path,
                json={"checkpoint_code": "ICP-PETRAPOLE-02"},
            )
            self.assertEqual(without_csrf.status_code, 403)
            switched = client.post(
                switch_path,
                headers={"X-CSRF-Token": login.json()["csrf_token"]},
                json={"checkpoint_code": "ICP-PETRAPOLE-02"},
            )
            self.assertEqual(switched.status_code, 200, switched.text)
            self.assertEqual(
                switched.json()["officer"]["active_checkpoint"]["code"],
                "ICP-PETRAPOLE-02",
            )
            logout = client.post(
                "/api/v1/auth/logout",
                headers={"X-CSRF-Token": login.json()["csrf_token"]},
            )
            self.assertEqual(logout.status_code, 204, logout.text)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_complete_mock_screening_lifecycle(self):
        with (
            patch("backend.main.ocr_service.extract", return_value=passport_ocr_items()),
            patch("backend.main._new_verifier", side_effect=FakeVerifier),
            self.authenticated_client() as client,
        ):
            created = client.post(
                "/api/v1/screenings",
                files={"document": ("passport.png", mock_png(), "image/png")},
            )
            self.assertEqual(created.status_code, 201, created.text)
            session_id = created.json()["session_id"]

            started = client.post(
                f"/api/v1/screenings/{session_id}/face/start"
            )
            self.assertEqual(started.status_code, 200, started.text)

            frame = client.post(
                f"/api/v1/screenings/{session_id}/face/frame",
                files={"frame": ("frame.png", mock_png(), "image/png")},
            )
            self.assertEqual(frame.status_code, 200, frame.text)
            self.assertTrue(frame.json()["face"]["verification_passed"])

            finalized = client.post(
                f"/api/v1/screenings/{session_id}/finalize",
                json={
                    "watchlist": {"blacklisted": False},
                    "border_context": {
                        "checkpoint_code": "ICP-MOREH-03",
                        "movement": "ENTRY",
                    },
                },
            )
            self.assertEqual(finalized.status_code, 200, finalized.text)
            self.assertEqual(finalized.json()["final"]["decision"], "APPROVE")
            self.assertEqual(
                finalized.json()["final"]["secondary_inspection"]["status"],
                "CLEAR",
            )
            self.assertEqual(
                finalized.json()["final"]["border_context"]["checkpoint_code"],
                "ICP-ATTARI-01",
            )

            disposition = client.post(
                f"/api/v1/screenings/{session_id}/disposition",
                json={
                    "decision": "CLEARED",
                    "reason_code": "AUTOMATED_CHECKS_CLEAR",
                    "notes": "All automated checks and live comparison reviewed.",
                },
            )
            self.assertEqual(disposition.status_code, 200, disposition.text)
            human_result = disposition.json()["final"]["officer_disposition"]
            self.assertEqual(human_result["decision"], "CLEARED")
            self.assertEqual(human_result["officer_username"], "integration-officer")
            self.assertFalse(human_result["overrides_automated_triage"])

            fetched = client.get(f"/api/v1/screenings/{session_id}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(
                fetched.json()["final"]["officer_disposition"]["decision"],
                "CLEARED",
            )

            deleted = client.delete(f"/api/v1/screenings/{session_id}")
            missing = client.get(f"/api/v1/screenings/{session_id}")
            missing_audit = client.get(f"/api/v1/screenings/{session_id}/audit")

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing_audit.status_code, 404)

    def test_rejects_non_image_upload(self):
        with self.authenticated_client() as client:
            response = client.post(
                "/api/v1/screenings",
                files={"document": ("document.txt", b"not an image", "text/plain")},
            )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["detail"]["code"], "UNSUPPORTED_MEDIA_TYPE")

    def test_creates_two_sided_aadhaar_screening_from_secure_qr(self):
        verification = {
            "signature_valid": True,
            "provider": "UIDAI",
            "method": "AADHAAR_SECURE_QR",
            "signature_algorithm": "SHA256withRSA",
            "certificate": {
                "filename": "uidai-test.cer",
                "subject": "O=UNIQUE IDENTIFICATION AUTHORITY OF INDIA",
                "sha256_fingerprint": "ABCD",
            },
            "fields": {
                "name": "JANE ALICE DOE",
                "reference_id": "456720260829123456789",
                "aadhaar_last_four": "4567",
                "date_of_birth": "1990-01-01",
                "sex": "F",
                "photo": mock_png(),
            },
        }
        front_ocr = [
            {"text": "Government of India", "confidence": 0.99},
            {"text": "JANE ALICE DOE", "confidence": 0.99},
            {"text": "DOB: 01/01/1990", "confidence": 0.99},
            {"text": "Female", "confidence": 0.99},
            {"text": "XXXX XXXX 4567", "confidence": 0.99},
        ]
        session_id = None
        with (
            patch("backend.main.ocr_service.extract", return_value=front_ocr),
            patch("ai.document_analysis.secure_qr.read_qr_text", return_value="123"),
            patch("ai.document_analysis.secure_qr.decode_secure_qr", return_value=verification),
            patch(
                "ai.face_verification.document_portrait.compare_document_portraits",
                return_value={
                    "status": "MATCH",
                    "match": True,
                    "similarity": 0.72,
                    "source": "VISIBLE_PHOTO_VS_UIDAI_SIGNED_QR_PORTRAIT",
                },
            ),
            self.authenticated_client() as client,
        ):
            try:
                response = client.post(
                    "/api/v1/screenings/aadhaar-card",
                    files={
                        "front": ("front.png", mock_png(), "image/png"),
                        "back": ("back.png", mock_png(), "image/png"),
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                session_id = response.json()["session_id"]
                document = response.json()["document"]["documents"][0]
                self.assertEqual(document["issuer_verification"]["method"], "AADHAAR_SECURE_QR")
                self.assertTrue(document["cross_validation"]["valid"])
                self.assertEqual(document["identity"]["document_number_masked"], "XXXX XXXX 4567")
            finally:
                if session_id:
                    client.delete(f"/api/v1/screenings/{session_id}")

    def test_sqlite_watchlist_drives_final_decision(self):
        entry_id = None
        session_id = None
        with (
            patch("backend.main.ocr_service.extract", return_value=passport_ocr_items()),
            patch("backend.main._new_verifier", side_effect=FakeVerifier),
            self.authenticated_client() as client,
        ):
            try:
                watchlist = client.post(
                    "/api/v1/watchlist",
                    json={
                        "document_number": "A-123 4567",
                        "reason": "Synthetic API test entry",
                    },
                )
                self.assertEqual(watchlist.status_code, 201, watchlist.text)
                entry_id = watchlist.json()["id"]

                created = client.post(
                    "/api/v1/screenings",
                    files={"document": ("passport.png", mock_png(), "image/png")},
                )
                self.assertEqual(created.status_code, 201, created.text)
                session_id = created.json()["session_id"]

                self.assertEqual(
                    client.post(
                        f"/api/v1/screenings/{session_id}/face/start"
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    client.post(
                        f"/api/v1/screenings/{session_id}/face/frame",
                        files={"frame": ("frame.png", mock_png(), "image/png")},
                    ).status_code,
                    200,
                )

                finalized = client.post(
                    f"/api/v1/screenings/{session_id}/finalize",
                    json={},
                )
                self.assertEqual(finalized.status_code, 200, finalized.text)
                result = finalized.json()["final"]
                self.assertEqual(result["decision"], "REJECT")
                self.assertIn("WATCHLIST_MATCH", result["reasons"])

                audit = client.get(
                    f"/api/v1/screenings/{session_id}/audit"
                )
                self.assertEqual(audit.status_code, 200)
                self.assertEqual(
                    audit.json()["events"][-1]["event_type"],
                    "SCREENING_FINALIZED",
                )
            finally:
                if session_id:
                    client.delete(f"/api/v1/screenings/{session_id}")
                if entry_id:
                    client.delete(f"/api/v1/watchlist/{entry_id}")

    def test_same_identity_is_allowed_across_document_numbers(self):
        document_one = "Z9000001"
        document_two = "Z9000002"

        def items_for(number):
            items = passport_ocr_items()
            for item in items:
                if item["text"].startswith("Passport No:"):
                    item["text"] = f"Passport No: {number}"
                elif len(item["text"]) == 44 and not item["text"].startswith("P<"):
                    item["text"] = build_td3_line2(
                        document_field=f"{number}<"
                    )
            return items

        session_ids = []
        database.delete_face_embedding("A1234567")
        database.delete_face_embedding(document_one)
        database.delete_face_embedding(document_two)
        with (
            patch(
                "backend.main.ocr_service.extract",
                side_effect=[items_for(document_one), items_for(document_two)],
            ),
            patch("backend.main._new_verifier", side_effect=FakeVerifier),
            self.authenticated_client() as client,
        ):
            try:
                first = client.post(
                    "/api/v1/screenings",
                    files={"document": ("first.png", mock_png(), "image/png")},
                )
                self.assertEqual(first.status_code, 201, first.text)
                first_id = first.json()["session_id"]
                session_ids.append(first_id)
                self.assertFalse(client.post(
                    f"/api/v1/screenings/{first_id}/face/start"
                ).json()["duplicate_identity"]["duplicate_identity"])
                client.post(
                    f"/api/v1/screenings/{first_id}/face/frame",
                    files={"frame": ("frame.png", mock_png(), "image/png")},
                )
                first_final = client.post(
                    f"/api/v1/screenings/{first_id}/finalize",
                    json={"border_context": {
                        "checkpoint_code": "ICP-ATTARI-01",
                        "movement": "ENTRY",
                        "lane": "LANE-01",
                    }},
                )
                self.assertEqual(first_final.json()["final"]["decision"], "APPROVE")
                self.assertEqual(
                    first_final.json()["final"]["continuity"]["status"],
                    "NEW_TRAVELLER",
                )

                second = client.post(
                    "/api/v1/screenings",
                    files={"document": ("second.png", mock_png(), "image/png")},
                )
                self.assertEqual(second.status_code, 201, second.text)
                second_id = second.json()["session_id"]
                session_ids.append(second_id)
                duplicate = client.post(
                    f"/api/v1/screenings/{second_id}/face/start"
                )
                self.assertEqual(duplicate.status_code, 200, duplicate.text)
                self.assertFalse(
                    duplicate.json()["duplicate_identity"]["duplicate_identity"]
                )
                self.assertTrue(
                    duplicate.json()["duplicate_identity"]["same_identity_matches"]
                )

                client.post(
                    f"/api/v1/screenings/{second_id}/face/frame",
                    files={"frame": ("frame.png", mock_png(), "image/png")},
                )
                switched = client.post(
                    "/api/v1/auth/active-checkpoint",
                    json={"checkpoint_code": "ICP-PETRAPOLE-02"},
                )
                self.assertEqual(switched.status_code, 200, switched.text)
                second_final = client.post(
                    f"/api/v1/screenings/{second_id}/finalize",
                    json={"border_context": {
                        "checkpoint_code": "ICP-PETRAPOLE-02",
                        "movement": "EXIT",
                    }},
                )
                self.assertEqual(second_final.json()["final"]["decision"], "APPROVE")
                continuity = second_final.json()["final"]["continuity"]
                self.assertEqual(continuity["status"], "CONTINUITY_CONFIRMED")
                self.assertEqual(continuity["prior_crossing_count"], 1)
                self.assertEqual(
                    continuity["timeline"][0]["checkpoint_code"],
                    "ICP-ATTARI-01",
                )
                checkpoint_labels = {
                    node["label"]
                    for node in continuity["graph"]["nodes"]
                    if node["type"] == "checkpoint"
                }
                self.assertEqual(checkpoint_labels, {
                    "ICP-ATTARI-01",
                    "ICP-PETRAPOLE-02",
                })
                self.assertNotIn(
                    "POSSIBLE_MULTIPLE_IDENTITIES",
                    second_final.json()["final"]["reasons"],
                )
                enrolled = [
                    record
                    for record in database.list_face_embeddings()
                    if record["document_number"] in {document_one, document_two}
                ]
                self.assertEqual(len(enrolled), 2)
                self.assertEqual(
                    {record["identity_id"] for record in enrolled},
                    {first_id},
                )
            finally:
                for session_id in session_ids:
                    client.delete(f"/api/v1/screenings/{session_id}")
                database.delete_face_embedding(document_one)
                database.delete_face_embedding(document_two)

    def test_same_face_conflicting_identity_links_prior_border_crossing(self):
        first_document = "Y8000001"
        second_document = "Y8000002"

        def conflicting_items(number, name, birth_display, birth_mrz):
            items = passport_ocr_items()
            for item in items:
                text = item["text"]
                if text.startswith("Name:"):
                    item["text"] = f"Name: {name}"
                elif text.startswith("Date of Birth:"):
                    item["text"] = f"Date of Birth: {birth_display}"
                elif text.startswith("Passport No:"):
                    item["text"] = f"Passport No: {number}"
                elif text.startswith("P<"):
                    surname, given = name.split(" ", 1)
                    item["text"] = f"P<IND{surname}<<{given}".ljust(44, "<")
                elif len(text) == 44:
                    item["text"] = build_td3_line2(
                        document_field=f"{number}<",
                        date_of_birth=birth_mrz,
                    )
            return items

        session_ids = []
        database.delete_face_embedding(first_document)
        database.delete_face_embedding(second_document)
        with (
            patch(
                "backend.main.ocr_service.extract",
                side_effect=[
                    conflicting_items(
                        first_document, "JANE DOE", "01/01/1990", "900101"
                    ),
                    conflicting_items(
                        second_document, "JOHN SMITH", "02/02/1985", "850202"
                    ),
                ],
            ),
            patch("backend.main._new_verifier", side_effect=FakeVerifier),
            self.authenticated_client() as client,
        ):
            try:
                first = client.post(
                    "/api/v1/screenings",
                    files={"document": ("first.png", mock_png(), "image/png")},
                )
                first_id = first.json()["session_id"]
                session_ids.append(first_id)
                client.post(f"/api/v1/screenings/{first_id}/face/start")
                client.post(
                    f"/api/v1/screenings/{first_id}/face/frame",
                    files={"frame": ("frame.png", mock_png(), "image/png")},
                )
                first_final = client.post(
                    f"/api/v1/screenings/{first_id}/finalize",
                    json={"border_context": {
                        "checkpoint_code": "ICP-ATTARI-01",
                        "movement": "ENTRY",
                    }},
                )
                self.assertEqual(first_final.json()["final"]["decision"], "APPROVE")

                second = client.post(
                    "/api/v1/screenings",
                    files={"document": ("second.png", mock_png(), "image/png")},
                )
                second_id = second.json()["session_id"]
                session_ids.append(second_id)
                duplicate = client.post(
                    f"/api/v1/screenings/{second_id}/face/start"
                )
                self.assertTrue(
                    duplicate.json()["duplicate_identity"]["duplicate_identity"]
                )
                client.post(
                    f"/api/v1/screenings/{second_id}/face/frame",
                    files={"frame": ("frame.png", mock_png(), "image/png")},
                )
                switched = client.post(
                    "/api/v1/auth/active-checkpoint",
                    json={"checkpoint_code": "ICP-PETRAPOLE-02"},
                )
                self.assertEqual(switched.status_code, 200, switched.text)
                second_final = client.post(
                    f"/api/v1/screenings/{second_id}/finalize",
                    json={"border_context": {
                        "checkpoint_code": "ICP-PETRAPOLE-02",
                        "movement": "EXIT",
                    }},
                )
                result = second_final.json()["final"]
                self.assertEqual(result["decision"], "REJECT")
                self.assertEqual(
                    result["continuity"]["status"],
                    "IDENTITY_CONFLICT",
                )
                self.assertEqual(
                    result["continuity"]["alerts"][0]["code"],
                    "SAME_FACE_DIFFERENT_IDENTITY",
                )
                self.assertEqual(
                    result["continuity"]["timeline"][0]["checkpoint_code"],
                    "ICP-ATTARI-01",
                )
            finally:
                for session_id in session_ids:
                    client.delete(f"/api/v1/screenings/{session_id}")
                database.delete_face_embedding(first_document)
                database.delete_face_embedding(second_document)


if __name__ == "__main__":
    unittest.main()
