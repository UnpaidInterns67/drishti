"""Lightweight OCR-text document classification."""


KEYWORDS = {
    "aadhaar": (
        "AADHAAR",
        "AADHAR",
        "UNIQUE IDENTIFICATION AUTHORITY OF INDIA",
        "GOVERNMENT OF INDIA",
        "YEAR OF BIRTH",
        "DOB",
    ),
    "visa": ("VISA", "NUMBER OF ENTRIES", "DURATION OF STAY", "VALID UNTIL"),
    "passport": ("PASSPORT", "NATIONALITY", "PLACE OF BIRTH", "P<"),
    "driving_license": ("DRIVING LICENCE", "DRIVING LICENSE", "DRIVER LICENSE"),
    "national_id": ("NATIONAL ID", "IDENTITY CARD", "IDENTITY NUMBER"),
    "permit": ("RESIDENCE PERMIT", "WORK PERMIT", "ENTRY PERMIT"),
}

# Explicit credential titles carry more evidence than shared field labels such
# as "valid until" or "date of birth".  Without this weighting, a residence
# permit containing a validity date could tie with the visa profile.
PRIMARY_KEYWORDS = {
    "aadhaar": ("AADHAAR", "AADHAR", "UNIQUE IDENTIFICATION AUTHORITY OF INDIA"),
    "visa": ("VISA",),
    "passport": ("PASSPORT", "P<"),
    "driving_license": ("DRIVING LICENCE", "DRIVING LICENSE", "DRIVER LICENSE"),
    "national_id": ("NATIONAL ID", "IDENTITY CARD"),
    "permit": ("RESIDENCE PERMIT", "WORK PERMIT", "ENTRY PERMIT"),
}


def classify_document(ocr_items) -> dict:
    text = "\n".join(
        str(item.get("text", "")).upper()
        for item in ocr_items
    )
    scores = {}
    for document_type, keywords in KEYWORDS.items():
        primary = set(PRIMARY_KEYWORDS.get(document_type, ()))
        scores[document_type] = sum(
            (3 if keyword in primary else 1)
            for keyword in keywords
            if keyword in text
        )
    best_type = max(scores, key=scores.get) if scores else "unknown"
    best_score = scores.get(best_type, 0)

    if best_score == 0:
        best_type = "unknown"

    matched_keywords = [
        keyword
        for keyword in KEYWORDS.get(best_type, ())
        if keyword in text
    ]
    primary = set(PRIMARY_KEYWORDS.get(best_type, ()))
    possible = sum(
        3 if keyword in primary else 1
        for keyword in KEYWORDS.get(best_type, ())
    ) or 1

    return {
        "document_type": best_type,
        "confidence": round(best_score / possible, 3),
        "matched_keywords": matched_keywords,
        "scores": scores,
    }
