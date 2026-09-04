import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ai.document_analysis.secure_qr import build_secure_qr_document
from ai.face_verification.document_portrait import compare_document_portraits
from ai.verification_engine import combine_verification
from mock_data import passing_face_result


class FakeFaceEngine:
    def __init__(self, similarity):
        self.similarity = similarity

    def detect_faces(self, _image):
        face = np.zeros((1, 15), dtype=np.float32)
        face[0, :4] = [10, 10, 100, 100]
        face[0, -1] = 0.99
        return face

    @staticmethod
    def largest_face(faces):
        return faces[0]

    @staticmethod
    def embedding(_image, _face):
        return np.ones((1, 128), dtype=np.float32)

    def cosine_similarity(self, _first, _second):
        return self.similarity

    @staticmethod
    def box(face):
        return tuple(int(value) for value in face[:4])

    @staticmethod
    def confidence(face):
        return float(face[-1])


def verification():
    return {
        "provider": "UIDAI",
        "method": "AADHAAR_SECURE_QR",
        "signature_valid": True,
        "signature_algorithm": "SHA256withRSA",
        "certificate": {"filename": "uidai.cer", "subject": "UIDAI"},
        "fields": {
            "name": "TEST PERSON",
            "aadhaar_last_four": "8000",
            "date_of_birth": "2000-01-01",
            "sex": "M",
        },
    }


class DocumentPortraitTests(unittest.TestCase):
    def compare(self, similarity):
        with tempfile.TemporaryDirectory() as directory:
            visible = Path(directory) / "visible.png"
            signed = Path(directory) / "signed.png"
            image = np.full((300, 500, 3), 127, dtype=np.uint8)
            cv2.imwrite(str(visible), image)
            cv2.imwrite(str(signed), image)
            return compare_document_portraits(
                visible,
                signed,
                engine=FakeFaceEngine(similarity),
            )

    def test_detects_visible_photo_replacement(self):
        result = self.compare(0.20)

        self.assertEqual(result["status"], "MISMATCH")
        self.assertFalse(result["match"])
        self.assertEqual(
            result["source"],
            "VISIBLE_PHOTO_VS_UIDAI_SIGNED_QR_PORTRAIT",
        )

    def test_accepts_consistent_visible_and_signed_portraits(self):
        result = self.compare(0.62)

        self.assertEqual(result["status"], "MATCH")
        self.assertTrue(result["match"])

    def test_photo_replacement_rejects_even_when_live_face_matches_signed_qr(self):
        portrait_check = self.compare(0.20)
        document_result = build_secure_qr_document(
            verification(),
            {
                "name": "TEST PERSON",
                "document_number": "XXXX XXXX 8000",
                "date_of_birth": "2000-01-01",
                "sex": "M",
            },
            portrait_check,
        )
        decision = combine_verification(document_result, passing_face_result())

        document = document_result["documents"][0]
        self.assertIn("AADHAAR_PHOTO_QR_MISMATCH", document["validation"]["issues"])
        self.assertEqual(document["risk"]["risk_score"], 100)
        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("AADHAAR_PHOTO_QR_MISMATCH", decision["reasons"])
        self.assertTrue(decision["checks"]["face_match"])


if __name__ == "__main__":
    unittest.main()
