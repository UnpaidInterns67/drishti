import unittest

from ai.document_analysis.authenticity import assess_authenticity


class AuthenticityAssessmentTests(unittest.TestCase):
    def test_mrz_checksum_is_not_mislabeled_as_issuer_authentication(self):
        result = assess_authenticity({
            "document_type": "passport",
            "mrz": {"detected": True, "checksums": {"valid": True}},
        })

        self.assertEqual(result["assurance_level"], "MACHINE_CONSISTENCY_ONLY")
        self.assertEqual(result["status"], "ISSUER_NOT_VERIFIED")
        self.assertEqual(result["checks"][-1]["check"], "E_PASSPORT_CHIP")
        self.assertEqual(result["checks"][-1]["status"], "NOT_PERFORMED")

    def test_valid_signature_produces_cryptographic_assurance(self):
        result = assess_authenticity({
            "document_type": "aadhaar",
            "issuer_verification": {
                "provider": "UIDAI",
                "method": "AADHAAR_SECURE_QR",
                "signature_valid": True,
            },
            "mrz": {"required": False, "detected": False},
        })

        self.assertEqual(result["status"], "ISSUER_VERIFIED")
        self.assertEqual(result["assurance_level"], "CRYPTOGRAPHIC_ISSUER_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
