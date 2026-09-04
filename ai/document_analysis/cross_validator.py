import re
from datetime import datetime


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_value(value):
    """
    Normalize OCR text for comparison.
    """

    if value is None:
        return ""

    value = str(value).upper().strip()

    value = re.sub(
        r"[^A-Z0-9]",
        "",
        value
    )

    return value


# =========================================================
# DATE VARIANTS
# =========================================================

def date_variants(date_string):
    """
    Generate common OCR representations of a date.

    Example:
        1983-02-09

    becomes:

        09021983
        09/02/1983
        09-02-1983
        09.02.1983
        09 FEB 1983
    """

    if not date_string:
        return []

    try:

        date = datetime.strptime(
            date_string,
            "%Y-%m-%d"
        )

    except ValueError:

        return []

    day = date.strftime("%d")
    month = date.strftime("%m")
    year = date.strftime("%Y")

    month_name = date.strftime("%b").upper()

    return [
        f"{day}{month}{year}",
        f"{day}/{month}/{year}",
        f"{day}-{month}-{year}",
        f"{day}.{month}.{year}",
        f"{day} {month_name} {year}",
        f"{day}{month}{year}"
    ]


# =========================================================
# GET NON-MRZ OCR TEXT
# =========================================================

def get_visual_text(ocr_items, mrz_raw=None):

    visual_text = []

    mrz_normalized = set()

    if mrz_raw:

        if isinstance(mrz_raw, list):

            for line in mrz_raw:

                mrz_normalized.add(
                    normalize_value(line)
                )

        else:

            mrz_normalized.add(
                normalize_value(mrz_raw)
            )

    for item in ocr_items:

        text = item.get(
            "text",
            ""
        )

        if not text:
            continue

        normalized = normalize_value(text)

        # Don't compare MRZ against itself
        if normalized in mrz_normalized:
            continue

        visual_text.append(
            text
        )

    return visual_text


# =========================================================
# SEARCH OCR
# =========================================================

def search_ocr(
    visual_text,
    variants
):

    normalized_lines = [
        normalize_value(text)
        for text in visual_text
    ]

    for variant in variants:

        normalized_variant = normalize_value(
            variant
        )

        if not normalized_variant:
            continue

        for line in normalized_lines:

            if normalized_variant in line:

                return True

    return False


def document_number_variants(mrz_value):
    """
    Generate variants of document numbers to account for common OCR substitution errors.
    E.g., Indian Passport 'Z9999999' misread as '29999999'.
    """
    if not mrz_value:
        return []

    cleaned = normalize_value(mrz_value)
    variants = {cleaned}

    # Fix OCR misreading leading 'Z' as '2' for Indian Passports (1 letter + 7 digits)
    if len(cleaned) == 8 and cleaned[0] == "Z" and cleaned[1:].isdigit():
        variants.add("2" + cleaned[1:])
    elif len(cleaned) == 8 and cleaned[0] == "2" and cleaned[1:].isdigit():
        variants.add("Z" + cleaned[1:])

    # Additional common OCR visual confusion maps (O <-> 0, I <-> 1)
    # can be added here if needed.

    return list(variants)


# =========================================================
# DOCUMENT NUMBER
# =========================================================

def compare_document_number(
    visual_text,
    mrz_value
):

    if not mrz_value:

        return {
            "status": "NOT_AVAILABLE",
            "match": None
        }

    # Use variants instead of exact string matching
    variants = document_number_variants(mrz_value)

    found = search_ocr(
        visual_text,
        variants
    )

    if found:

        return {
            "status": "MATCH",
            "match": True,
            "source": "OCR"
        }

    return {
        "status": "NOT_FOUND",
        "match": None,
        "source": "OCR"
    }

# =========================================================
# DATE
# =========================================================

def compare_date(
    visual_text,
    mrz_value,
    field_name
):

    if not mrz_value:

        return {
            "status": "NOT_AVAILABLE",
            "match": None
        }

    variants = date_variants(
        mrz_value
    )

    found = search_ocr(
        visual_text,
        variants
    )

    if found:

        return {
            "status": "MATCH",
            "match": True,
            "source": "OCR",
            "field": field_name
        }

    return {
        "status": "NOT_FOUND",
        "match": None,
        "source": "OCR",
        "field": field_name
    }


# =========================================================
# SEX
# =========================================================

def compare_sex(
    visual_text,
    mrz_value
):

    if not mrz_value:

        return {
            "status": "NOT_AVAILABLE",
            "match": None
        }

    normalized_lines = [
        normalize_value(text)
        for text in visual_text
    ]

    # We only claim a match when we find an explicit
    # gender/sex indicator.
    target_values = []

    if mrz_value == "M":

        target_values = [
            "SEX M",
            "SEX:M",
            "GENDER M",
            "GENDER:M",
            "MALE"
        ]

    elif mrz_value == "F":

        target_values = [
            "SEX F",
            "SEX:F",
            "GENDER F",
            "GENDER:F",
            "FEMALE"
        ]

    for target in target_values:

        normalized_target = normalize_value(
            target
        )

        for line in normalized_lines:

            if normalized_target in line:

                return {
                    "status": "MATCH",
                    "match": True,
                    "source": "OCR"
                }

    return {
        "status": "NOT_FOUND",
        "match": None,
        "source": "OCR"
    }


def compare_structured_value(visual_value, machine_value, field_name):
    """Compare independently extracted visible and machine-readable values."""
    if visual_value in (None, "") or machine_value in (None, ""):
        return None
    if field_name == "name":
        # Visible zones and MRZs commonly reverse surname/given-name order.
        visible_tokens = sorted(re.findall(r"[A-Z0-9]+", str(visual_value).upper()))
        machine_tokens = sorted(re.findall(r"[A-Z0-9]+", str(machine_value).upper()))
        match = visible_tokens == machine_tokens
    else:
        match = normalize_value(visual_value) == normalize_value(machine_value)
    return {
        "status": "MATCH" if match else "MISMATCH",
        "match": match,
        "source": "VISIBLE_ZONE_VS_MRZ",
        "field": field_name,
        "visible_value": visual_value,
        "machine_value": machine_value,
    }


# =========================================================
# CROSS VALIDATE ONE DOCUMENT
# =========================================================

def cross_validate_document(
    document,
    ocr_items
):

    identity = document.get(
        "identity",
        {}
    )

    mrz = document.get(
        "mrz",
        {}
    )

    mrz_raw = mrz.get(
        "raw"
    )

    visual_text = get_visual_text(
        ocr_items,
        mrz_raw
    )

    results = {

        "document_number":
            compare_document_number(
                visual_text,
                identity.get(
                    "document_number"
                )
            ),

        "date_of_birth":
            compare_date(
                visual_text,
                identity.get(
                    "date_of_birth"
                ),
                "date_of_birth"
            ),

        "date_of_expiry":
            compare_date(
                visual_text,
                identity.get(
                    "date_of_expiry"
                ),
                "date_of_expiry"
            ),

        "sex":
            compare_sex(
                visual_text,
                identity.get(
                    "sex"
                )
            )
    }


    # When both sources were independently extracted, an explicit difference
    # is stronger evidence than searching unstructured OCR text.  The raw MRZ
    # is excluded above so this cannot accidentally compare the MRZ to itself.
    if mrz.get("detected", False):
        visual_fields = document.get("visual_zone", {}).get("fields", {})
        for field_name in (
            "name",
            "document_number",
            "date_of_birth",
            "date_of_expiry",
            "sex",
        ):
            structured = compare_structured_value(
                visual_fields.get(field_name),
                identity.get(field_name),
                field_name,
            )
            if structured is not None:
                results[field_name] = structured

    # -----------------------------------------------------
    # Determine overall status
    # -----------------------------------------------------

    confirmed_matches = 0
    not_found = 0
    mismatches = 0

    for result in results.values():

        status = result["status"]

        if status == "MATCH":

            confirmed_matches += 1

        elif status == "NOT_FOUND":

            not_found += 1

        elif status == "MISMATCH":

            mismatches += 1

    # IMPORTANT:
    #
    # NOT_FOUND does NOT mean mismatch.
    #
    # OCR may simply fail to detect a visible field.
    #

    if mismatches > 0:

        overall_status = "MISMATCH"

    elif confirmed_matches > 0:

        overall_status = "CONSISTENT_WITH_OCR"

    else:

        overall_status = "INSUFFICIENT_OCR_EVIDENCE"

    return {

        "overall_status":
            overall_status,

        "confirmed_matches":
            confirmed_matches,

        "not_found":
            not_found,

        "mismatches":
            mismatches,

        "fields":
            results
    }


# =========================================================
# ALL DOCUMENTS
# =========================================================

def cross_validate_documents(
    documents,
    ocr_items
):

    results = []

    for document in documents:

        result = cross_validate_document(
            document,
            ocr_items
        )

        results.append(
            result
        )

    return results
