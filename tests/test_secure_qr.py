import gzip
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID

from ai.document_analysis.secure_qr import (
    SecureQrError,
    build_secure_qr_document,
    decode_secure_qr,
)


def certificate_and_key(directory: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "UNIQUE IDENTIFICATION AUTHORITY OF INDIA (UIDAI)"),
        x509.NameAttribute(NameOID.COMMON_NAME, "UIDAI TEST SECURE QR"),
    ])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    (directory / "uidai_12_06_18_cer.cer").write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    return key


def qr_decimal(key, *, name="JANE ALICE DOE", last_four="4567"):
    values = (
        "0",
        f"{last_four}20260829123456789",
        name,
        "01-01-1990",
        "F",
        "D/O TEST",
        "NEW DELHI",
        "",
        "42",
        "CENTRAL",
        "110001",
        "GPO",
        "DELHI",
        "MAIN ROAD",
        "NEW DELHI",
        "NEW DELHI",
    )
    signed = b"\xff".join(value.encode("iso-8859-1") for value in values) + b"\xff" + b"mock-jp2-photo"
    signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    compressed = gzip.compress(signed + signature)
    return str(int.from_bytes(compressed, "big"))


def qr_decimal_v3(key, *, name="JANE ALICE DOE", last_four="8000"):
    values = (
        "V3",
        "2",
        f"{last_four}20260829123456789",
        name,
        "30-11-2006",
        "F",
        "",
        "NEW DELHI",
        "NEAR TEST",
        "42",
        "CENTRAL",
        "110001",
        "GPO",
        "DELHI",
        "MAIN ROAD",
        "NEW DELHI",
        "NEW DELHI",
        "XXXXXX4567",
        "",
    )
    portrait = b"\xff\x4f\xff\x51mock-jp2-photo\xff\xd9"
    signed = b"\xff".join(value.encode("iso-8859-1") for value in values) + portrait
    signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    compressed = gzip.compress(signed + signature)
    return str(int.from_bytes(compressed, "big"))


class SecureQrTests(unittest.TestCase):
    def test_decodes_and_verifies_uidai_signed_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            key = certificate_and_key(directory)
            result = decode_secure_qr(qr_decimal(key), directory)

        self.assertTrue(result["signature_valid"])
        self.assertEqual(result["fields"]["aadhaar_last_four"], "4567")
        self.assertEqual(result["fields"]["date_of_birth"], "1990-01-01")
        self.assertEqual(result["fields"]["name"], "JANE ALICE DOE")

    def test_rejects_tampered_signed_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            key = certificate_and_key(directory)
            original = qr_decimal(key)
            payload = bytearray(gzip.decompress(int(original).to_bytes((int(original).bit_length() + 7) // 8, "big")))
            payload[10] ^= 1
            tampered = str(int.from_bytes(gzip.compress(bytes(payload)), "big"))
            with self.assertRaises(SecureQrError) as raised:
                decode_secure_qr(tampered, directory)

        self.assertEqual(raised.exception.code, "UIDAI_SECURE_QR_SIGNATURE_INVALID")

    def test_decodes_and_verifies_v3_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            key = certificate_and_key(directory)
            result = decode_secure_qr(qr_decimal_v3(key), directory)

        self.assertTrue(result["signature_valid"])
        self.assertEqual(result["format_version"], "V3")
        self.assertEqual(result["fields"]["version"], "V3")
        self.assertEqual(result["fields"]["aadhaar_last_four"], "8000")
        self.assertEqual(result["fields"]["date_of_birth"], "2006-11-30")
        self.assertEqual(result["fields"]["masked_mobile"], "XXXXXX4567")
        self.assertTrue(result["fields"]["photo"].startswith(b"\xff\x4f\xff\x51"))

    def test_front_mismatch_becomes_critical_document_risk(self):
        verification = {
            "provider": "UIDAI",
            "method": "AADHAAR_SECURE_QR",
            "signature_valid": True,
            "signature_algorithm": "SHA256withRSA",
            "certificate": {"filename": "uidai.cer", "subject": "UIDAI", "sha256_fingerprint": "AA"},
            "fields": {
                "name": "JANE ALICE DOE",
                "aadhaar_last_four": "4567",
                "date_of_birth": "1990-01-01",
                "sex": "F",
            },
        }
        result = build_secure_qr_document(
            verification,
            {"name": "OTHER PERSON", "document_number": "123412341111", "date_of_birth": "1991-02-02", "sex": "F"},
        )
        document = result["documents"][0]

        self.assertIn("AADHAAR_FRONT_QR_MISMATCH", document["validation"]["issues"])
        self.assertEqual(document["risk"]["risk_score"], 100)
        self.assertNotIn("123412341111", str(result))

    def test_single_digit_ocr_ambiguity_requests_recapture_not_tampering_reject(self):
        verification = {
            "provider": "UIDAI",
            "method": "AADHAAR_SECURE_QR",
            "signature_valid": True,
            "signature_algorithm": "SHA256withRSA",
            "certificate": {"filename": "uidai.cer", "subject": "UIDAI", "sha256_fingerprint": "AA"},
            "fields": {
                "name": "JANE ALICE DOE",
                "aadhaar_last_four": "8000",
                "date_of_birth": "1990-01-01",
                "sex": "F",
            },
        }
        result = build_secure_qr_document(
            verification,
            {"name": "JANE ALICE DOE", "document_number": "XXXX XXXX 8060", "date_of_birth": "1990-01-01", "sex": "F"},
        )
        document = result["documents"][0]

        self.assertIn("AADHAAR_FRONT_OCR_INCONCLUSIVE", document["validation"]["issues"])
        self.assertNotIn("AADHAAR_FRONT_QR_MISMATCH", document["validation"]["issues"])
        self.assertEqual(document["risk"]["risk_score"], 35)


if __name__ == "__main__":
    unittest.main()
