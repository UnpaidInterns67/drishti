import unittest

import numpy as np

from ai.face_verification.verifier import stable_similarity
from ai.secondary_inspection import build_secondary_inspection
from ai.verification_engine import combine_verification


def approved_result(face=None, watchlist=None):
    return {
        "decision": "APPROVE",
        "reasons": [],
        "biometrics": face or {
            "face_match": True,
            "liveness_passed": True,
            "face_similarity": 0.62,
            "face_match_threshold": 0.40,
            "quality": {"passed": True},
        },
        "watchlist": watchlist or {"match": False},
    }


class StableFaceSimilarityTests(unittest.TestCase):
    def test_uses_median_instead_of_one_outlier_frame(self):
        identity = np.array([1.0, 0.0])
        samples = [
            np.array([0.61, 0.0]),
            np.array([0.64, 0.0]),
            np.array([0.15, 0.0]),
        ]

        stats = stable_similarity(
            identity,
            samples,
            lambda _identity, sample: float(sample[0]),
        )

        self.assertEqual(stats["median"], 0.61)
        self.assertEqual(stats["samples"], 3)
        self.assertEqual(stats["minimum"], 0.15)


class SecondaryInspectionTests(unittest.TestCase):
    def test_clear_result_continues_standard_processing(self):
        inspection = build_secondary_inspection(
            approved_result(),
            {"status": "CONTINUITY_CONFIRMED", "summary": "Known traveller."},
        )

        self.assertEqual(inspection["status"], "CLEAR")
        self.assertEqual(
            inspection["primary_action"]["code"],
            "CLEAR_STANDARD_LANE",
        )

    def test_identity_conflict_requires_supervisor_resolution(self):
        inspection = build_secondary_inspection(
            approved_result(),
            {
                "status": "IDENTITY_CONFLICT",
                "summary": "Same face, conflicting profile.",
                "conflicting_fields": ["date_of_birth"],
            },
        )

        self.assertEqual(inspection["status"], "SUPERVISOR_REVIEW")
        self.assertEqual(
            inspection["primary_action"]["code"],
            "RESOLVE_IDENTITY_CONTINUITY",
        )

    def test_watchlist_signal_has_highest_priority(self):
        result = approved_result(watchlist={"match": True})
        result["reasons"] = ["WATCHLIST_MATCH"]

        inspection = build_secondary_inspection(result)

        self.assertEqual(inspection["status"], "DENY_AND_ESCALATE")
        self.assertEqual(inspection["priority"], "CRITICAL")

    def test_low_quality_capture_gives_specific_guidance(self):
        result = approved_result(face={
            "face_match": False,
            "liveness_passed": False,
            "quality": {
                "passed": False,
                "failures": ["too_dark", "image_blurry"],
            },
        })

        inspection = build_secondary_inspection(result)

        self.assertEqual(
            inspection["primary_action"]["code"],
            "GUIDED_BIOMETRIC_RECAPTURE",
        )
        self.assertIn("front lighting", inspection["primary_action"]["instruction"])

    def test_borderline_match_requests_second_capture(self):
        result = approved_result(face={
            "face_match": True,
            "liveness_passed": True,
            "face_similarity": 0.42,
            "face_match_threshold": 0.40,
            "face_match_margin": 0.04,
            "quality": {"passed": True},
        })

        inspection = build_secondary_inspection(result)

        self.assertEqual(inspection["status"], "ACTION_REQUIRED")
        self.assertEqual(
            inspection["primary_action"]["code"],
            "SECOND_INDEPENDENT_BIOMETRIC",
        )

    def test_combiner_does_not_approve_borderline_face(self):
        document = {
            "documents": [{
                "document_type": "other",
                "validation": {"validation_score": 100, "issues": []},
                "risk": {"decision": "PASS", "risk_score": 0},
            }]
        }
        face = {
            "face_match": True,
            "liveness_passed": True,
            "face_similarity": 0.42,
            "face_match_threshold": 0.40,
            "face_match_margin": 0.04,
        }

        result = combine_verification(document, face, {"match": False})

        self.assertEqual(result["decision"], "RETRY")
        self.assertIn("FACE_MATCH_BORDERLINE", result["reasons"])


if __name__ == "__main__":
    unittest.main()
