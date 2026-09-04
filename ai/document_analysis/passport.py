import re
from datetime import datetime


def clean_text(text: str) -> str:
    """Normalize OCR text."""
    text = text.upper().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def find_passport_number(texts):
    """
    Try to identify a passport number.

    Typical passport number:
    1 letter + 7 digits
    Example: A1234567
    """

    for text in texts:
        text = clean_text(text)

        labelled = re.search(
            r"\b(?:PASSPORT|DOCUMENT)\s*(?:NO\.?|NUMBER|#)\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9 -]{4,15})\b",
            text,
        )
        if labelled:
            candidate = re.sub(r"\s+", "", labelled.group(1))
            if re.fullmatch(r"[A-Z0-9]{5,12}", candidate):
                return candidate

        # Common passport-number pattern
        match = re.search(r"\b[A-Z]{1,2}[0-9]{6,8}\b", text)

        if match:
            return match.group()

    return None


def find_nationality(texts):
    """
    Look for a 3-letter nationality code.
    """

    common_codes = {
        "IND",
        "USA",
        "GBR",
        "CAN",
        "AUS",
        "DEU",
        "FRA",
        "JPN",
        "CHN",
        "BGD",
        "NPL",
        "ARE",
        "SGP",
    }

    for text in texts:
        text = clean_text(text)

        words = re.findall(r"\b[A-Z]{3}\b", text)

        for word in words:
            if word in common_codes:
                return word

    return None


def find_dates(texts):
    """
    Extract common passport dates.

    Supports examples like:
    12 MAY 2000
    12 MAY 2030
    12/05/2000
    12-05-2030
    """

    dates = []

    month_pattern = (
        r"\b\d{1,2}\s+"
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{4}\b"
    )

    numeric_pattern = r"\b\d{2}[/-]\d{2}[/-]\d{4}\b"

    for text in texts:
        text = clean_text(text)

        matches = re.findall(month_pattern, text)
        if matches:
            # Extract complete match separately
            complete = re.findall(
                r"\b\d{1,2}\s+"
                r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
                r"\s+\d{4}\b",
                text,
            )
            dates.extend(complete)

        dates.extend(re.findall(numeric_pattern, text))

    return dates


def _top_left(item):
    bbox = item.get("bbox") or [[0, 0]]
    return float(bbox[0][0]), float(bbox[0][1])


def _parse_visual_date(value):
    value = clean_text(value)
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def find_labeled_date(ocr_items, label_pattern):
    """Find the nearest date printed just below or beside a field label."""
    labels = []
    dates = []
    date_re = re.compile(
        r"\b(?:\d{2}[/-]\d{2}[/-]\d{4}|\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{4})\b"
    )

    for item in ocr_items:
        text = clean_text(item.get("text", ""))
        x, y = _top_left(item)
        label_match = re.search(label_pattern, text)
        if label_match:
            labels.append((x, y))
            # Prefer a date printed in the same OCR region as its label.  This
            # prevents adjacent DOB/expiry rows from tying spatially.
            inline_dates = list(date_re.finditer(text))
            if inline_dates:
                inline = _parse_visual_date(inline_dates[-1].group())
                if inline:
                    return inline
        for match in date_re.finditer(text):
            parsed = _parse_visual_date(match.group())
            if parsed:
                dates.append((x, y, parsed))

    candidates = []
    for label_x, label_y in labels:
        for date_x, date_y, parsed in dates:
            vertical_gap = date_y - label_y
            horizontal_gap = abs(date_x - label_x)
            if -20 <= vertical_gap <= 130 and horizontal_gap <= 500:
                candidates.append((max(vertical_gap, 0) + horizontal_gap * 0.15, parsed))
    return min(candidates)[1] if candidates else None


def find_name(texts):
    """
    Basic name extraction.

    This is intentionally conservative.
    We will improve it later using passport-region information.
    """

    ignored_words = {
        "PASSPORT",
        "REPUBLIC",
        "INDIA",
        "NATIONALITY",
        "DATE",
        "BIRTH",
        "EXPIRY",
        "SEX",
        "MALE",
        "FEMALE",
        "PLACE",
        "ISSUE",
        "AUTHORITY",
    }

    candidates = []

    for text in texts:
        text = clean_text(text)

        labelled = re.search(
            r"\b(?:FULL\s+NAME|NAME)\s*[:#-]\s*([A-Z][A-Z '-]{2,79})$",
            text,
        )
        if labelled:
            return labelled.group(1).strip()

        if len(text) < 4:
            continue

        if not re.fullmatch(r"[A-Z ]+", text):
            continue

        words = text.split()

        if any(word in ignored_words for word in words):
            continue

        if 2 <= len(words) <= 5:
            candidates.append(text)

    # First reasonable candidate
    if candidates:
        return candidates[0]

    return None


def find_labeled_text(ocr_items, label_pattern):
    """Extract a conservative inline or nearest-next-line labelled value."""
    ordered = sorted(ocr_items, key=lambda item: (_top_left(item)[1], _top_left(item)[0]))
    all_labels = re.compile(
        r"\b(?:NAME|NATIONALITY|SEX|GENDER|DATE|PLACE|AUTHORITY|PASSPORT)\b",
        re.IGNORECASE,
    )
    for index, item in enumerate(ordered):
        text = str(item.get("text", "")).strip()
        inline = re.search(
            rf"{label_pattern}\s*[:#-]\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        if inline and inline.group(1).strip():
            return inline.group(1).strip().upper()
        if re.search(label_pattern, text, re.IGNORECASE) and index + 1 < len(ordered):
            candidate = str(ordered[index + 1].get("text", "")).strip()
            if candidate and not all_labels.search(candidate):
                return candidate.upper()
    return None


def detect_sex(texts):
    """
    Detect passport sex field.
    """

    for text in texts:
        text = clean_text(text)

        if re.search(r"\bSEX\s*[:\-]?\s*M\b", text):
            return "M"

        if re.search(r"\bSEX\s*[:\-]?\s*F\b", text):
            return "F"

        if text == "M":
            return "M"

        if text == "F":
            return "F"

    return None


def analyze_passport(ocr_items):
    """
    Convert OCR output into structured passport information.
    """

    texts = [
        item["text"]
        for item in ocr_items
        if item.get("text")
    ]

    passport_number = find_passport_number(texts)
    nationality = find_nationality(texts)
    dates = find_dates(texts)
    name = find_name(texts)
    sex = detect_sex(texts)
    date_of_birth = find_labeled_date(ocr_items, r"\b(?:BIRTH|BITH|DOB)\b")
    # The bilingual specimen is often OCRed as "Expiny"; the stable EXPI
    # prefix is specific enough when combined with spatial date association.
    date_of_expiry = find_labeled_date(ocr_items, r"\bEXPI")
    date_of_issue = find_labeled_date(ocr_items, r"\b(?:DATE\s+OF\s+ISSUE|ISSUED\s+ON)\b")
    place_of_birth = find_labeled_text(ocr_items, r"\bPLACE\s+OF\s+BIRTH\b")
    place_of_issue = find_labeled_text(ocr_items, r"\bPLACE\s+OF\s+ISSUE\b")
    issuing_authority = find_labeled_text(
        ocr_items,
        r"\b(?:ISSUING\s+AUTHORITY|AUTHORITY)\b",
    )

    result = {
        "document_type": "passport",

        "fields": {
            "name": name,
            "document_number": passport_number,
            "nationality": nationality,
            "date_of_birth": date_of_birth,
            "date_of_expiry": date_of_expiry,
            "date_of_issue": date_of_issue,
            "place_of_birth": place_of_birth,
            "place_of_issue": place_of_issue,
            "issuing_authority": issuing_authority,
            "sex": sex
        },

        "dates_found": dates,

        "confidence": {
            "name": 0.0,
            "document_number": 0.0,
            "nationality": 0.0,
            "date_of_birth": 0.0,
            "date_of_expiry": 0.0,
            "date_of_issue": 0.0,
            "place_of_birth": 0.0,
            "place_of_issue": 0.0,
            "issuing_authority": 0.0,
            "sex": 0.0
        }
    }

    # We currently don't know which date is DOB/expiry
    # until MRZ is parsed.
    #
    # For now, keep all detected dates.

    if name:
        result["confidence"]["name"] = 0.70

    if passport_number:
        result["confidence"]["document_number"] = 0.90

    if nationality:
        result["confidence"]["nationality"] = 0.90

    if sex:
        result["confidence"]["sex"] = 0.80

    if date_of_birth:
        result["confidence"]["date_of_birth"] = 0.85

    if date_of_expiry:
        result["confidence"]["date_of_expiry"] = 0.85

    for optional_field in (
        "date_of_issue",
        "place_of_birth",
        "place_of_issue",
        "issuing_authority",
    ):
        if result["fields"][optional_field]:
            result["confidence"][optional_field] = 0.80

    return result
