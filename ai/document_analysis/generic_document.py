"""Conservative extraction for national IDs, driving licences, and permits.

The supported documents vary widely between issuing authorities.  This module
therefore extracts only explicitly labelled values and reports provenance for
every field instead of pretending that one layout covers every credential.
"""

from __future__ import annotations

import re
from datetime import datetime


DATE_TOKEN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{4}[./-]\d{1,2}[./-]\d{1,2}"
    r"|\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"\s+\d{2,4})"
)


FIELD_LABELS = {
    "name": (
        r"(?:FULL\s+NAME|HOLDER(?:'S)?\s+NAME|NAME)",
    ),
    "document_number": (
        r"(?:DOCUMENT|IDENTITY|ID|LICEN[CS]E|PERMIT|CARD)\s*"
        r"(?:NO\.?|NUMBER|#)",
        r"(?:DL|ID)\s*(?:NO\.?|NUMBER|#)",
    ),
    "date_of_birth": (r"(?:DATE\s+OF\s+BIRTH|DOB|BIRTH\s+DATE)",),
    "date_of_issue": (r"(?:DATE\s+OF\s+ISSUE|ISSUED\s+ON|ISSUE\s+DATE)",),
    "date_of_expiry": (
        r"(?:DATE\s+OF\s+EXPIRY|EXPIRY\s+DATE|EXPIRES|VALID\s+(?:UNTIL|TO))",
    ),
    "valid_from": (r"(?:VALID\s+FROM|VALIDITY\s+FROM)",),
    "nationality": (r"NATIONALITY",),
    "sex": (r"(?:SEX|GENDER)",),
    "issuing_authority": (r"(?:ISSUING\s+AUTHORITY|ISSUED\s+BY|AUTHORITY)",),
    "address": (r"ADDRESS",),
    "permit_type": (r"(?:PERMIT\s+TYPE|TYPE\s+OF\s+PERMIT|CATEGORY)",),
    "vehicle_classes": (r"(?:CLASS(?:ES)?|CATEGORIES|VEHICLE\s+CLASS)",),
    "blood_group": (r"BLOOD\s+GROUP",),
}


DATE_FIELDS = {"date_of_birth", "date_of_issue", "date_of_expiry", "valid_from"}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" :#|-"))


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _clean(value).upper().replace(".", "/")
    formats = (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %b %y",
    )
    for date_format in formats:
        try:
            parsed = datetime.strptime(cleaned, date_format)
            if parsed.year > datetime.now().year + 50:
                parsed = parsed.replace(year=parsed.year - 100)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _value_after_label(line: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"\b{label}\b\s*[:#-]?\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            value = _clean(match.group(1))
            if value:
                return value
    return None


def _contains_label(line: str, labels: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{label}\b", line, re.IGNORECASE) for label in labels)


def _extract_field(lines: list[str], field: str) -> tuple[object | None, dict | None]:
    labels = FIELD_LABELS[field]
    for index, line in enumerate(lines):
        value = _value_after_label(line, labels)
        source_line = index
        if value is None and _contains_label(line, labels) and index + 1 < len(lines):
            candidate = _clean(lines[index + 1])
            # Do not consume the next field label as a value.
            if candidate and not any(
                _contains_label(candidate, other_labels)
                for other_labels in FIELD_LABELS.values()
            ):
                value = candidate
                source_line = index + 1
        if value is None:
            continue

        if field in DATE_FIELDS:
            date_match = re.search(DATE_TOKEN, value, re.IGNORECASE)
            normalized = _normalize_date(date_match.group() if date_match else value)
            if normalized is None:
                continue
            value = normalized
        elif field == "sex":
            token = value.upper()
            if re.search(r"\b(?:F|FEMALE)\b", token):
                value = "F"
            elif re.search(r"\b(?:M|MALE)\b", token):
                value = "M"
            elif re.search(r"\b(?:X|OTHER|NON[- ]?BINARY)\b", token):
                value = "X"
            else:
                continue
        elif field == "nationality":
            code = re.search(r"\b[A-Z]{3}\b", value.upper())
            value = code.group() if code else value.upper()
        elif field == "document_number":
            number = re.search(r"[A-Z0-9][A-Z0-9 /.-]{2,31}", value.upper())
            if not number:
                continue
            value = re.sub(r"\s+", "", number.group().strip(" ./-"))
        elif field == "vehicle_classes":
            value = [
                part.strip().upper()
                for part in re.split(r"[,/]", value)
                if part.strip()
            ]
        else:
            value = value.upper()

        return value, {
            "source": "VISIBLE_ZONE_OCR",
            "line_index": source_line,
            "raw_text": lines[source_line],
        }
    return None, None


def analyze_generic_document(ocr_items: list[dict], document_type: str) -> dict:
    """Extract a common, auditable field set from a labelled credential."""
    if document_type not in {"national_id", "driving_license", "permit"}:
        raise ValueError(f"Unsupported generic document type: {document_type}")

    lines = [_clean(item.get("text", "")) for item in ocr_items]
    lines = [line for line in lines if line]
    common_fields = [
        "name",
        "document_number",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
        "nationality",
        "sex",
        "issuing_authority",
        "address",
    ]
    type_fields = {
        "national_id": [],
        "driving_license": ["vehicle_classes", "blood_group"],
        "permit": ["permit_type", "valid_from"],
    }

    fields = {}
    provenance = {}
    for field in common_fields + type_fields[document_type]:
        value, source = _extract_field(lines, field)
        fields[field] = value
        if source:
            provenance[field] = source

    expected = {
        "national_id": ("name", "document_number", "date_of_birth"),
        "driving_license": (
            "name",
            "document_number",
            "date_of_birth",
            "date_of_expiry",
        ),
        "permit": ("name", "document_number", "date_of_expiry", "permit_type"),
    }[document_type]
    present = sum(bool(fields.get(field)) for field in expected)

    return {
        "document_type": document_type,
        "fields": fields,
        "field_provenance": provenance,
        "extraction_confidence": round(present / len(expected), 3),
        "missing_fields": [field for field in expected if not fields.get(field)],
        "limitations": [
            "Visible-zone OCR is not issuer authentication",
            "Country-specific templates should be configured for production",
        ],
    }
