"""Rule-based extraction and validation helpers for Indian Aadhaar cards."""

from __future__ import annotations

import re
from datetime import datetime


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

# Replacement cost models common OCR *readings*. For example, a printed zero
# is frequently returned as a six, so correcting a read "6" back to "0" is a
# stronger candidate than assuming a read "0" was really a printed six.
_OCR_DIGIT_CONFUSIONS = {
    "0": (("8", 2), ("6", 2)),
    "1": (("7", 2),),
    "3": (("8", 2),),
    "5": (("6", 2),),
    "6": (("0", 1), ("5", 2), ("8", 2)),
    "7": (("1", 2),),
    "8": (("3", 2), ("0", 2), ("6", 2)),
}


def verhoeff_valid(value: str | None) -> bool:
    """Return whether a complete Aadhaar number has a valid check digit."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 12:
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[index % 8][int(digit)]]
    return checksum == 0


def correct_aadhaar_number(value: str | None) -> tuple[str | None, list[dict]]:
    """Apply one unambiguous, checksum-supported OCR digit correction.

    Verhoeff alone is not strong enough to guess freely. Correction is limited
    to one common visual substitution and is applied only when exactly one
    valid candidate has the best (lowest) confusion cost.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 12 or verhoeff_valid(digits):
        return (digits or None), []

    candidates = []
    for index, source in enumerate(digits):
        for replacement, cost in _OCR_DIGIT_CONFUSIONS.get(source, ()):
            candidate = digits[:index] + replacement + digits[index + 1:]
            if verhoeff_valid(candidate):
                candidates.append((cost, candidate, index, source, replacement))

    if not candidates:
        return digits, []
    best_cost = min(candidate[0] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate[0] == best_cost]
    if len(best) != 1:
        return digits, []

    cost, corrected, index, source, replacement = best[0]
    return corrected, [{
        "field": "document_number",
        "position": index,
        "from": source,
        "to": replacement,
        "reason": "AADHAAR_VERHOEFF_CHECKSUM",
        "confidence": "LIKELY" if cost == 1 else "POSSIBLE",
        "independently_verified": False,
        "requires_manual_review": True,
    }]


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[.\-]", "/", value.strip())
    for date_format in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _extract_document_number(lines: list[str]) -> tuple[str | None, bool]:
    # Do not mistake the 16-digit Virtual ID or phone numbers for Aadhaar.
    for line in lines:
        if re.search(r"\bVID\b", line, re.IGNORECASE):
            continue
        masked = re.search(
            r"(?:X{4}|\*{4})[\s-]*(?:X{4}|\*{4})[\s-]*(\d{4})\b",
            line,
            re.IGNORECASE,
        )
        if masked:
            return masked.group(1), True

        match = re.search(r"(?<!\d)(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})(?!\d)", line)
        if match:
            return "".join(match.groups()), False
    return None, False


def _extract_birth(lines: list[str]) -> tuple[str | None, bool, int | None]:
    for index, line in enumerate(lines):
        dob = re.search(
            r"(?:DOB|DATE\s+OF\s+BIRTH)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
            line,
            re.IGNORECASE,
        )
        if dob:
            return _normalize_date(dob.group(1)), False, index

        yob = re.search(
            r"(?:YOB|YEAR\s+OF\s+BIRTH)\s*[:\-]?\s*((?:19|20)\d{2})",
            line,
            re.IGNORECASE,
        )
        if yob:
            return yob.group(1), True, index
    return None, False, None


def _extract_sex(lines: list[str]) -> str | None:
    text = "\n".join(lines)
    if re.search(r"\b(?:FEMALE|GENDER\s*[:\-]?\s*F)\b", text, re.IGNORECASE):
        return "F"
    if re.search(r"\b(?:MALE|GENDER\s*[:\-]?\s*M)\b", text, re.IGNORECASE):
        return "M"
    if re.search(r"\bTRANSGENDER\b", text, re.IGNORECASE):
        return "X"
    return None


def _name_candidate(line: str) -> bool:
    normalized = " ".join(line.upper().split())
    if not re.fullmatch(r"[A-Z][A-Z .'-]{2,59}", normalized):
        return False
    ignored = (
        "GOVERNMENT", "INDIA", "AADHAAR", "AADHAR", "AUTHORITY", "IDENTIFICATION",
        "DOB", "BIRTH", "MALE", "FEMALE", "ADDRESS", "VID", "ENROLMENT", "HELP",
    )
    return not any(word in normalized for word in ignored)


def _extract_name(lines: list[str], birth_index: int | None) -> str | None:
    if birth_index is not None:
        for line in reversed(lines[max(0, birth_index - 4):birth_index]):
            if _name_candidate(line):
                return " ".join(line.upper().split())
    for line in lines:
        if _name_candidate(line) and 2 <= len(line.split()) <= 5:
            return " ".join(line.upper().split())
    return None


def analyze_aadhaar(ocr_items) -> dict:
    lines = [
        " ".join(str(item.get("text", "")).strip().split())
        for item in ocr_items
        if str(item.get("text", "")).strip()
    ]
    document_number, masked = _extract_document_number(lines)
    ocr_corrections = []
    if document_number and not masked:
        document_number, ocr_corrections = correct_aadhaar_number(document_number)
    date_of_birth, birth_year_only, birth_index = _extract_birth(lines)
    fields = {
        "name": _extract_name(lines, birth_index),
        "document_number": document_number,
        "document_number_masked": (
            f"XXXX XXXX {document_number}" if masked and document_number else
            f"XXXX XXXX {document_number[-4:]}" if document_number else None
        ),
        "aadhaar_masked": masked,
        "ocr_corrections": ocr_corrections,
        "date_of_birth": date_of_birth,
        "birth_year_only": birth_year_only,
        "sex": _extract_sex(lines),
        "nationality": "IND",
    }
    required = ("name", "document_number", "date_of_birth", "sex")
    extracted = sum(bool(fields.get(field)) for field in required)
    return {
        "document_type": "aadhaar",
        "fields": fields,
        "extraction_confidence": round(extracted / len(required), 3),
        "missing_fields": [field for field in required if not fields.get(field)],
        "ocr_corrections": ocr_corrections,
    }
