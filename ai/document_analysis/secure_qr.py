"""Decode and verify the digitally signed Secure QR printed on Aadhaar.

Supported layouts are the legacy binary payload and UIDAI's newer ``V3``
payload. Both use decimal BigInteger -> gzip -> signed data -> 256-byte RSA
signature. V3 prefixes a version field and places masked contact values before
the JPEG 2000 portrait.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


MAX_QR_DIGITS = 20_000
MAX_DECOMPRESSED_BYTES = 128 * 1024
SIGNATURE_BYTES = 256
DEMOGRAPHIC_FIELDS = (
    "contact_indicator",
    "reference_id",
    "name",
    "date_of_birth",
    "sex",
    "care_of",
    "district",
    "landmark",
    "house",
    "location",
    "postal_code",
    "post_office",
    "state",
    "street",
    "subdistrict",
    "vtc",
)
V3_TEXT_FIELDS = ("version", *DEMOGRAPHIC_FIELDS, "masked_mobile", "masked_email")
SECURE_QR_CERTIFICATES = (
    "uidai_secure_qr_ds_05.pem",
    "uidai_12_06_18_cer.cer",
    "uidai_prod_cdup.cer",
)
JPEG2000_START = b"\xff\x4f\xff\x51"
JPEG2000_END = b"\xff\xd9"


class SecureQrError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VerifiedCertificate:
    certificate: x509.Certificate
    filename: str


def _read_barcode_with_zxing(image: np.ndarray) -> str | None:
    try:
        import zxingcpp
    except ImportError:
        return None
    result = zxingcpp.read_barcode(image)
    return result.text.strip() if result and result.text else None


def read_qr_text(image_path: str | Path) -> str:
    """Read a high-density QR using ZXing, with OpenCV as a fallback."""
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SecureQrError("AADHAAR_BACK_IMAGE_INVALID", "The Aadhaar back image could not be decoded.")

    candidates = [image]
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest < 2400:
        scale = min(3.0, 2400 / longest)
        candidates.append(cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))

    detector = cv2.QRCodeDetector()
    for candidate in candidates:
        text = _read_barcode_with_zxing(candidate)
        if text:
            return text
        text, _points, _straight = detector.detectAndDecode(candidate)
        if text:
            return text.strip()

    raise SecureQrError(
        "AADHAAR_SECURE_QR_NOT_DETECTED",
        "Secure QR could not be read from the Aadhaar back. Upload a sharp, uncropped back-side image.",
    )


def _load_certificate(path: Path) -> x509.Certificate:
    data = path.read_bytes()
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError:
        return x509.load_der_x509_certificate(data)


def _trusted_certificates(directory: str | Path) -> list[VerifiedCertificate]:
    directory = Path(directory)
    certificates = []
    for filename in SECURE_QR_CERTIFICATES:
        path = directory / filename
        if path.is_file():
            certificate = _load_certificate(path)
            subject = certificate.subject.rfc4514_string().upper()
            if "UIDAI" not in subject and "UNIQUE IDENTIFICATION" not in subject:
                continue
            certificates.append(VerifiedCertificate(certificate, filename))
    if not certificates:
        raise SecureQrError(
            "UIDAI_SECURE_QR_CERTIFICATE_MISSING",
            "The server has no trusted UIDAI Secure QR certificate configured.",
        )
    return certificates


def _decompress_decimal_payload(qr_text: str) -> bytes:
    value = re.sub(r"\s+", "", qr_text)
    if not value.isdecimal() or not (1 <= len(value) <= MAX_QR_DIGITS):
        raise SecureQrError("AADHAAR_SECURE_QR_FORMAT_INVALID", "The QR payload is not a UIDAI decimal payload.")
    integer = int(value)
    compressed = integer.to_bytes((integer.bit_length() + 7) // 8, "big")
    try:
        payload = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise SecureQrError("AADHAAR_SECURE_QR_FORMAT_INVALID", "The Secure QR payload is damaged.") from exc
    if not payload or len(payload) > MAX_DECOMPRESSED_BYTES:
        raise SecureQrError("AADHAAR_SECURE_QR_SIZE_INVALID", "The Secure QR payload has an unsafe size.")
    return payload


def _verify_signature(signed_data: bytes, signature: bytes, directory: str | Path) -> VerifiedCertificate:
    for trusted in _trusted_certificates(directory):
        try:
            trusted.certificate.public_key().verify(
                signature,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return trusted
        except InvalidSignature:
            continue
    raise SecureQrError(
        "UIDAI_SECURE_QR_SIGNATURE_INVALID",
        "The Aadhaar Secure QR signature is invalid; the QR data may have been altered.",
    )


def _normalise_date(value: str) -> str | None:
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}", value):
        return value
    return None


def _decode_text_fields(values: list[bytes], names: tuple[str, ...]) -> dict[str, str]:
    if len(values) != len(names):
        raise SecureQrError(
            "AADHAAR_SECURE_QR_FORMAT_INVALID",
            "The Secure QR demographic fields are incomplete.",
        )
    try:
        return {
            name: value.decode("iso-8859-1").strip()
            for name, value in zip(names, values, strict=True)
        }
    except UnicodeDecodeError as exc:
        raise SecureQrError(
            "AADHAAR_SECURE_QR_FORMAT_INVALID",
            "The Secure QR demographic text is invalid.",
        ) from exc


def _parse_v3(signed_data: bytes) -> tuple[dict[str, str], bytes, int]:
    photo_start = signed_data.find(JPEG2000_START)
    photo_end = signed_data.find(JPEG2000_END, photo_start)
    if photo_start < 0 or photo_end < 0 or photo_end + len(JPEG2000_END) != len(signed_data):
        raise SecureQrError(
            "AADHAAR_SECURE_QR_PHOTO_INVALID",
            "The signed V3 Secure QR portrait is missing or malformed.",
        )
    fields = _decode_text_fields(signed_data[:photo_start].split(b"\xff"), V3_TEXT_FIELDS)
    if fields["version"] != "V3":
        raise SecureQrError(
            "AADHAAR_SECURE_QR_VERSION_UNSUPPORTED",
            f"Secure QR version {fields['version']!r} is not supported.",
        )
    photo = signed_data[photo_start : photo_end + len(JPEG2000_END)]
    return fields, photo, int(fields["contact_indicator"])


def _parse_legacy(signed_data: bytes) -> tuple[dict[str, str], bytes, int]:
    fields: dict[str, str] = {}
    cursor = 0
    for name in DEMOGRAPHIC_FIELDS:
        delimiter = signed_data.find(b"\xff", cursor)
        if delimiter < 0:
            raise SecureQrError(
                "AADHAAR_SECURE_QR_FORMAT_INVALID",
                "The Secure QR demographic fields are incomplete.",
            )
        fields[name] = signed_data[cursor:delimiter].decode("iso-8859-1").strip()
        cursor = delimiter + 1

    indicator = int(fields["contact_indicator"])
    hash_bytes = 32 * ((1 if indicator & 1 else 0) + (1 if indicator & 2 else 0))
    photo_end = len(signed_data) - hash_bytes
    if photo_end <= cursor:
        raise SecureQrError("AADHAAR_SECURE_QR_PHOTO_INVALID", "The signed QR portrait is missing.")
    return fields, signed_data[cursor:photo_end], indicator


def decode_secure_qr(qr_text: str, certificate_directory: str | Path) -> dict:
    payload = _decompress_decimal_payload(qr_text)
    if len(payload) <= SIGNATURE_BYTES:
        raise SecureQrError("AADHAAR_SECURE_QR_FORMAT_INVALID", "The Secure QR payload is incomplete.")
    signed_data, signature = payload[:-SIGNATURE_BYTES], payload[-SIGNATURE_BYTES:]
    trusted = _verify_signature(signed_data, signature, certificate_directory)

    try:
        if signed_data.startswith(b"V3\xff"):
            fields, photo, indicator = _parse_v3(signed_data)
        elif re.match(rb"V\d+\xff", signed_data):
            version = signed_data.split(b"\xff", 1)[0].decode("ascii", errors="replace")
            raise SecureQrError(
                "AADHAAR_SECURE_QR_VERSION_UNSUPPORTED",
                f"Secure QR version {version!r} is not supported.",
            )
        else:
            fields, photo, indicator = _parse_legacy(signed_data)
    except ValueError as exc:
        raise SecureQrError("AADHAAR_SECURE_QR_FORMAT_INVALID", "The Secure QR contact indicator is invalid.") from exc
    if indicator not in (0, 1, 2, 3):
        raise SecureQrError("AADHAAR_SECURE_QR_FORMAT_INVALID", "The Secure QR contact indicator is invalid.")

    reference_id = fields["reference_id"]
    last_four = reference_id[:4] if re.match(r"^\d{4}", reference_id) else None
    dob = _normalise_date(fields["date_of_birth"])
    sex = fields["sex"].upper()[:1]
    if not last_four or not fields["name"] or not dob or sex not in {"M", "F", "T"}:
        raise SecureQrError("AADHAAR_SECURE_QR_IDENTITY_INVALID", "Required signed identity fields are missing.")

    certificate = trusted.certificate
    return {
        "provider": "UIDAI",
        "method": "AADHAAR_SECURE_QR",
        "format_version": fields.get("version", "legacy"),
        "signature_valid": True,
        "signature_algorithm": "SHA256withRSA",
        "certificate": {
            "filename": trusted.filename,
            "subject": certificate.subject.rfc4514_string(),
            "sha256_fingerprint": certificate.fingerprint(hashes.SHA256()).hex().upper(),
        },
        "fields": {
            **fields,
            "aadhaar_last_four": last_four,
            "date_of_birth": dob,
            "sex": "X" if sex == "T" else sex,
            "photo": photo,
            "email_hash_present": bool(indicator & 1),
            "mobile_hash_present": bool(indicator & 2),
        },
    }


def _normalise_text(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def cross_check_front(front_identity: dict, signed_fields: dict) -> dict:
    """Compare printed front-side OCR with the issuer-signed QR identity."""
    checks = {}
    unreadable = []
    inconclusive = []
    mismatched = []
    front_name = _normalise_text(front_identity.get("name"))
    signed_name = _normalise_text(signed_fields.get("name"))
    if not front_name:
        checks["name"] = None
        unreadable.append("name")
    else:
        checks["name"] = SequenceMatcher(None, front_name, signed_name).ratio() >= 0.82
        if not checks["name"]:
            mismatched.append("name")

    front_dob = _normalise_date(str(front_identity.get("date_of_birth") or ""))
    signed_dob = signed_fields.get("date_of_birth")
    if not front_dob:
        checks["date_of_birth"] = None
        unreadable.append("date_of_birth")
    else:
        checks["date_of_birth"] = front_dob == signed_dob
        if not checks["date_of_birth"]:
            mismatched.append("date_of_birth")

    front_number = re.sub(r"\D", "", str(front_identity.get("document_number") or ""))
    if len(front_number) < 4:
        checks["aadhaar_last_four"] = None
        unreadable.append("aadhaar_last_four")
    else:
        printed, signed = front_number[-4:], signed_fields["aadhaar_last_four"]
        distance = sum(left != right for left, right in zip(printed, signed))
        checks["aadhaar_last_four"] = distance == 0
        if distance == 1:
            inconclusive.append("aadhaar_last_four")
        elif distance > 1:
            mismatched.append("aadhaar_last_four")
    return {
        "source": "AADHAAR_FRONT_VS_UIDAI_SECURE_QR",
        "checks": checks,
        "mismatches": len(mismatched),
        "mismatched_fields": mismatched,
        "unreadable_fields": unreadable,
        "inconclusive_fields": inconclusive,
        "valid": not mismatched and not unreadable and not inconclusive,
    }


def build_secure_qr_document(
    verification: dict,
    front_identity: dict,
    portrait_cross_check: dict | None = None,
) -> dict:
    from .authenticity import assess_authenticity
    from .risk_engine import calculate_risk
    from .validation import validate_document

    fields = verification["fields"]
    cross_validation = cross_check_front(front_identity, fields)
    if portrait_cross_check is not None:
        cross_validation["portrait"] = portrait_cross_check
        portrait_status = portrait_cross_check.get("status")
        if portrait_status == "MISMATCH":
            cross_validation["mismatches"] += 1
            cross_validation["mismatched_fields"].append("portrait")
            cross_validation["valid"] = False
        elif portrait_status == "INCONCLUSIVE":
            cross_validation["inconclusive_fields"].append("portrait")
            cross_validation["valid"] = False
    front_number = re.sub(r"\D", "", str(front_identity.get("document_number") or ""))
    safe_front_identity = {
        "name": front_identity.get("name"),
        "date_of_birth": front_identity.get("date_of_birth"),
        "sex": front_identity.get("sex"),
        "document_number_masked": f"XXXX XXXX {front_number[-4:]}" if len(front_number) >= 4 else None,
    }
    identity = {
        "name": fields["name"],
        "document_number": fields["aadhaar_last_four"],
        "document_number_masked": f"XXXX XXXX {fields['aadhaar_last_four']}",
        "aadhaar_masked": True,
        "date_of_birth": fields["date_of_birth"],
        "sex": fields["sex"],
        "nationality": "IND",
        "address": {
            key: fields.get(key)
            for key in ("care_of", "house", "street", "landmark", "location", "vtc", "post_office", "district", "subdistrict", "state", "postal_code")
            if fields.get(key)
        },
    }
    document = {
        "document_type": "aadhaar",
        "identity": identity,
        "issuer_verification": {key: value for key, value in verification.items() if key != "fields"},
        "extraction": {
            "source": "UIDAI_SIGNED_SECURE_QR",
            "confidence": 1.0,
            "ocr_corrections": [],
            "front_ocr_identity": safe_front_identity,
        },
        "cross_validation": cross_validation,
        "mrz": {"required": False, "detected": False},
        "expiry": {"status": "NOT_APPLICABLE"},
    }
    document["validation"] = validate_document(document)
    if cross_validation["mismatched_fields"]:
        demographic_mismatch = any(
            field != "portrait"
            for field in cross_validation["mismatched_fields"]
        )
        if demographic_mismatch:
            document["validation"]["issues"].append("AADHAAR_FRONT_QR_MISMATCH")
        if "portrait" in cross_validation["mismatched_fields"]:
            document["validation"]["issues"].append("AADHAAR_PHOTO_QR_MISMATCH")
    elif any(
        field != "portrait"
        for field in (
            cross_validation["unreadable_fields"]
            + cross_validation["inconclusive_fields"]
        )
    ):
        document["validation"]["issues"].append("AADHAAR_FRONT_OCR_INCONCLUSIVE")
    if (
        portrait_cross_check is not None
        and portrait_cross_check.get("status") == "INCONCLUSIVE"
    ):
        document["validation"]["issues"].append("AADHAAR_PHOTO_QR_INCONCLUSIVE")
    document["validation"]["issues"] = list(dict.fromkeys(
        document["validation"]["issues"]
    ))
    document["authenticity"] = assess_authenticity(document)
    document["risk"] = calculate_risk(document)
    return {
        "classification": {"document_type": "aadhaar", "confidence": 1.0, "scores": {"aadhaar": 1.0}},
        "document_count": 1,
        "documents": [document],
    }
