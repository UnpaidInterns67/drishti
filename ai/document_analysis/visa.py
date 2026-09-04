"""Rule-based extraction for common machine-printed visa fields."""

import re
from datetime import datetime


DATE_PATTERN = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"


def _normalize_date(value):
    if not value:
        return None
    cleaned = value.replace(".", "/").replace("-", "/")
    for date_format in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _match(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" :<")
    return None


def analyze_visa(ocr_items) -> dict:
    lines = [str(item.get("text", "")).strip() for item in ocr_items]
    text = "\n".join(lines)

    visa_number = _match(text, (
        r"VISA\s*(?:NO|NUMBER|#)\s*[:#-]?\s*([A-Z0-9]{5,16})",
        r"VAF\s*(?:NO|NUMBER)?\s*[:#-]?\s*([A-Z0-9]{5,16})",
    ))
    visa_type = _match(text, (
        r"VISA\s*TYPE\s*[:#-]?\s*([A-Z][A-Z0-9 -]{0,19})",
        r"TYPE\s*[:#-]\s*([A-Z][A-Z0-9 -]{0,19})",
    ))
    entries = _match(text, (
        r"(?:NUMBER\s+OF\s+)?ENTR(?:Y|IES)\s*[:#-]?\s*(SINGLE|DOUBLE|MULTIPLE|\d+)",
    ))
    duration = _match(text, (
        r"DURATION(?:\s+OF\s+STAY)?\s*[:#-]?\s*(\d{1,3})\s*DAYS?",
    ))
    valid_from_raw = _match(text, (
        rf"VALID\s+FROM\s*[:#-]?\s*({DATE_PATTERN})",
        rf"FROM\s*[:#-]\s*({DATE_PATTERN})",
    ))
    valid_until_raw = _match(text, (
        rf"VALID\s+(?:UNTIL|TO)\s*[:#-]?\s*({DATE_PATTERN})",
        rf"UNTIL\s*[:#-]?\s*({DATE_PATTERN})",
    ))
    holder_name = _match(text, (
        r"(?:HOLDER(?:'S)?\s+NAME|FULL\s+NAME|NAME)\s*[:#-]\s*([A-Z][A-Z '-]{2,79})",
    ))
    passport_number = _match(text, (
        r"PASSPORT\s*(?:NO|NUMBER|#)\s*[:#-]?\s*([A-Z0-9]{5,12})",
        r"TRAVEL\s+DOCUMENT\s*(?:NO|NUMBER|#)\s*[:#-]?\s*([A-Z0-9]{5,16})",
    ))
    nationality = _match(text, (
        r"NATIONALITY\s*[:#-]?\s*([A-Z]{3})\b",
    ))
    date_of_birth_raw = _match(text, (
        rf"(?:DATE\s+OF\s+BIRTH|DOB)\s*[:#-]?\s*({DATE_PATTERN})",
    ))
    issuing_authority = _match(text, (
        r"(?:ISSUING\s+AUTHORITY|ISSUED\s+BY)\s*[:#-]\s*([A-Z][A-Z0-9 .'-]{2,79})",
    ))

    fields = {
        "visa_number": visa_number,
        "visa_type": visa_type,
        "entries": entries.upper() if entries else None,
        "valid_from": _normalize_date(valid_from_raw),
        "valid_until": _normalize_date(valid_until_raw),
        "stay_duration_days": int(duration) if duration else None,
        "name": holder_name.upper() if holder_name else None,
        "passport_number": passport_number.upper() if passport_number else None,
        "nationality": nationality.upper() if nationality else None,
        "date_of_birth": _normalize_date(date_of_birth_raw),
        "issuing_authority": issuing_authority.upper() if issuing_authority else None,
    }
    required_fields = (
        "visa_number",
        "visa_type",
        "entries",
        "valid_from",
        "valid_until",
        "stay_duration_days",
    )
    extracted = sum(fields[field] is not None for field in required_fields)

    return {
        "document_type": "visa",
        "fields": fields,
        "extraction_confidence": round(extracted / len(required_fields), 3),
        "missing_fields": [name for name in required_fields if fields[name] is None],
    }
