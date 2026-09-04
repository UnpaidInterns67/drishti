import unittest

from ai.verification_engine import combine_verification


def document_result(**overrides):
    document = {
        "mrz": {"detected": True},
        "expiry": {"status": "VALID"},
        "validation": {"validation_score": 100, "issues": []},
        "cross_validation": {"mismatches": 0},
        "risk": {"decision": "PASS"},
    }
    document.update(overrides)
    return {"documents": [document]}


def face_result(**overrides):
    result = {
        "face_match": True,
        "liveness_passed": True,
    }
    result.update(overrides)
    return result


class CombineVerificationTests(unittest.TestCase):
    def test_approves_when_every_check_passes(self):
        result = combine_verification(document_result(), face_result())

        self.assertTrue(result["verified"])
        self.assertEqual(result["decision"], "APPROVE")
        self.assertEqual(result["reasons"], [])

    def test_rejects_an_expired_document(self):
        result = combine_verification(
            document_result(expiry={"status": "EXPIRED"}),
            face_result(),
        )

        self.assertFalse(result["verified"])
        self.assertIn("DOCUMENT_EXPIRED", result["reasons"])

    def test_rejects_failed_biometrics(self):
        result = combine_verification(
            document_result(),
            face_result(face_match=False, liveness_passed=False),
        )

        self.assertFalse(result["verified"])
        self.assertIn("LIVENESS_FAILED", result["reasons"])
        self.assertIn("FACE_MISMATCH", result["reasons"])

    def test_rejects_missing_document_result(self):
        result = combine_verification({"documents": []}, face_result())

        self.assertFalse(result["verified"])
        self.assertIn("NO_DOCUMENT_RESULT", result["reasons"])

    def test_rejects_multiple_document_records(self):
        document = document_result()["documents"][0]
        result = combine_verification(
            {"documents": [document, document]},
            face_result(),
        )

        self.assertFalse(result["verified"])
        self.assertIn("MULTIPLE_DOCUMENT_RECORDS", result["reasons"])

    def test_sends_moderate_tampering_signal_to_automated_retry(self):
        result = combine_verification(
            document_result(
                forensics={"overall": {"tampering_score": 45, "signals": []}}
            ),
            face_result(),
        )

        self.assertEqual(result["decision"], "RETRY")
        self.assertFalse(result["manual_review"])
        self.assertTrue(result["retry_required"])
        self.assertIn("POSSIBLE_TAMPERING", result["reasons"])

    def test_single_weak_forensic_signal_does_not_block_approval(self):
        result = combine_verification(
            document_result(
                forensics={
                    "overall": {
                        "tampering_score": 25,
                        "signals": [{"signal": "NOISE_INCONSISTENCY"}],
                    },
                },
            ),
            face_result(),
        )

        self.assertEqual(result["decision"], "APPROVE")
        self.assertTrue(result["verified"])

    def test_rejects_watchlist_match(self):
        result = combine_verification(
            document_result(),
            face_result(),
            {"blacklisted": True},
        )

        self.assertEqual(result["decision"], "REJECT")
        self.assertEqual(result["risk_score"], 100)
        self.assertIn("WATCHLIST_MATCH", result["reasons"])

    def test_rejects_invalid_uidai_signature_as_critical(self):
        result = combine_verification(
            document_result(
                issuer_verification={
                    "provider": "UIDAI",
                    "signature_valid": False,
                }
            ),
            face_result(),
        )

        self.assertEqual(result["decision"], "REJECT")
        self.assertEqual(result["risk_score"], 100)
        self.assertIn("UIDAI_SIGNATURE_INVALID", result["reasons"])

    def test_returns_explainable_evidence(self):
        result = combine_verification(
            document_result(),
            face_result(face_match=False),
        )

        face_evidence = next(
            item for item in result["evidence"]
            if item["code"] == "FACE_MISMATCH"
        )
        self.assertEqual(face_evidence["severity"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
