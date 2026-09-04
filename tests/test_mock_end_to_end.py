import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ai.document_analysis.analyzer import build_document_record
from ai.face_verification.config import (
    HEAD_CENTER_FRAMES,
    HEAD_TURN_FRAMES,
    MIN_CLOSED_FRAMES,
)
from ai.face_verification.face_engine import FaceEngine
from ai.face_verification.identity_search import find_duplicate_identities
from ai.face_verification.liveness import LivenessDetector
from ai.image_forensics.forensic_engine import analyze_image_forensics
from ai.verification_engine import combine_verification
from mock_data import passport_ocr_items, passing_face_result, visa_ocr_items


class MockEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.face_engine = FaceEngine()

    def test_valid_passport_full_decision(self):
        document_result = build_document_record(passport_ocr_items())
        document = document_result["documents"][0]
        decision = combine_verification(document_result, passing_face_result())

        self.assertEqual(document_result["classification"]["document_type"], "passport")
        self.assertTrue(document["mrz"]["checksums"]["valid"])
        self.assertEqual(document["identity"]["name"], "JANE ALICE DOE")
        self.assertEqual(document["validation"]["validation_score"], 100)
        self.assertEqual(document["risk"]["decision"], "PASS")
        self.assertEqual(decision["decision"], "APPROVE")

    def test_mrz_tampering_reaches_manual_review(self):
        document_result = build_document_record(
            passport_ocr_items(tamper_mrz=True)
        )
        decision = combine_verification(document_result, passing_face_result())

        self.assertFalse(
            document_result["documents"][0]["mrz"]["checksums"]["valid"]
        )
        self.assertEqual(decision["decision"], "RETRY")
        self.assertIn("MRZ_CHECKSUM_FAILED", decision["reasons"])

    def test_valid_visa_full_decision(self):
        document_result = build_document_record(visa_ocr_items())
        decision = combine_verification(document_result, passing_face_result())

        self.assertEqual(document_result["documents"][0]["document_type"], "visa")
        self.assertEqual(decision["decision"], "APPROVE")

    def test_duplicate_identity_reaches_rejection(self):
        duplicate = find_duplicate_identities(
            [1.0, 0.0, 0.0],
            [{
                "identity_id": "existing-person",
                "document_number": "OLD00001",
                "full_name": "OTHER PERSON",
                "date_of_birth": "1985-05-05",
                "embedding": [0.99, 0.01, 0.0],
            }],
            document_number="A1234567",
            full_name="KUMAR G",
            date_of_birth="1994-07-01",
            threshold=0.8,
        )
        decision = combine_verification(
            build_document_record(passport_ocr_items()),
            passing_face_result(),
            {"duplicate_identity": duplicate["duplicate_identity"]},
        )

        self.assertTrue(duplicate["duplicate_identity"])
        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("POSSIBLE_MULTIPLE_IDENTITIES", decision["reasons"])

    def test_blacklist_reaches_rejection(self):
        decision = combine_verification(
            build_document_record(passport_ocr_items()),
            passing_face_result(),
            {"document_blacklisted": True},
        )

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("WATCHLIST_MATCH", decision["reasons"])

    def test_image_forensics_on_synthetic_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mock_document.jpg"
            image = Image.new("RGB", (800, 500), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 780, 480), outline="navy", width=4)
            draw.rectangle((40, 100, 240, 350), fill="lightgray")
            draw.text((280, 100), "MOCK PASSPORT A1234567", fill="black")
            image.save(path, quality=92)

            result = analyze_image_forensics(path)
            document_result = build_document_record(
                passport_ocr_items(),
                image_path=path,
            )

        self.assertIn("tampering_score", result["overall"])
        self.assertIn("quality_score", result["overall"])
        self.assertEqual(len(result["metadata"]["sha256"]), 64)
        self.assertGreaterEqual(result["overall"]["tampering_score"], 0)
        self.assertLessEqual(result["overall"]["tampering_score"], 100)
        self.assertIn("forensics", document_result["documents"][0])
        self.assertIn("risk_score", document_result["documents"][0]["risk"])

    def test_face_models_reject_blank_mock_image(self):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        faces = self.face_engine.detect_faces(blank)

        self.assertEqual(len(faces), 0)

    def test_face_embedding_on_specimen_document(self):
        specimen = Path(__file__).parents[1] / "datasets" / "raw" / "passport_001.png"
        if not specimen.is_file():
            self.skipTest("Optional local specimen is not distributed with the public repository")
        image = cv2.imread(str(specimen))
        self.assertIsNotNone(image)

        faces = self.face_engine.detect_faces(image)
        self.assertGreater(len(faces), 0)
        face = self.face_engine.largest_face(faces)
        embedding = self.face_engine.embedding(image, face)
        similarity = self.face_engine.cosine_similarity(embedding, embedding)

        self.assertEqual(list(embedding.shape), [1, 128])
        self.assertAlmostEqual(similarity, 1.0, places=5)

    def test_randomized_liveness_state_machine(self):
        detector = LivenessDetector()
        try:
            self.assertIn(detector.required_turn_direction, {"LEFT", "RIGHT"})

            for _ in range(MIN_CLOSED_FRAMES):
                detector._process_blink(0.10)
            detector._process_blink(0.30)
            self.assertEqual(detector.state, "TURN_HEAD")

            turn_signal = (
                -0.20 if detector.required_turn_direction == "LEFT" else 0.20
            )
            for _ in range(HEAD_TURN_FRAMES):
                detector._process_head_turn(turn_signal)
            self.assertEqual(detector.state, "RETURN_CENTER")

            for _ in range(HEAD_CENTER_FRAMES):
                detector._process_return_center(0.0)
            self.assertEqual(detector.state, "PASSED")
            self.assertEqual(detector.score(), 1.0)
        finally:
            detector.close()


if __name__ == "__main__":
    unittest.main()
