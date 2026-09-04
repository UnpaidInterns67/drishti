"""ICAO Doc 9303 helpers for machine-readable travel documents."""

ICAO_WEIGHTS = (7, 3, 1)


def character_value(character: str) -> int:
    """Return the ICAO numeric value for an MRZ character."""
    if character == "<":
        return 0
    if character.isdigit():
        return int(character)
    if "A" <= character <= "Z":
        return ord(character) - ord("A") + 10
    raise ValueError(f"Invalid MRZ character: {character!r}")


def calculate_check_digit(value: str) -> str:
    """Calculate an ICAO modulus-10 check digit using 7-3-1 weights."""
    total = sum(
        character_value(character) * ICAO_WEIGHTS[index % 3]
        for index, character in enumerate(value)
    )
    return str(total % 10)


def validate_check_digit(value: str, expected: str) -> dict:
    """Return an explainable check-digit result."""
    calculated = calculate_check_digit(value)
    normalized_expected = "0" if expected == "<" else expected
    return {
        "valid": normalized_expected.isdigit()
        and calculated == normalized_expected,
        "expected": expected,
        "calculated": calculated,
    }


def validate_td3_line2(line2: str, document_field: str | None = None) -> dict:
    """Validate all check digits in a 44-character TD3 lower MRZ line."""
    normalized = line2.upper().replace(" ", "")
    structurally_valid = len(normalized) == 44
    normalized = normalized[:44].ljust(44, "<")

    document_field = document_field or normalized[0:9]
    document_number = validate_check_digit(document_field, normalized[9])
    date_of_birth = validate_check_digit(normalized[13:19], normalized[19])
    date_of_expiry = validate_check_digit(normalized[21:27], normalized[27])
    optional_data = validate_check_digit(normalized[28:42], normalized[42])

    composite_data = (
        document_field
        + normalized[9]
        + normalized[13:20]
        + normalized[21:43]
    )
    composite = validate_check_digit(composite_data, normalized[43])

    checks = {
        "document_number": document_number,
        "date_of_birth": date_of_birth,
        "date_of_expiry": date_of_expiry,
        "optional_data": optional_data,
        "composite": composite,
    }

    required_checks = (
        document_number,
        date_of_birth,
        date_of_expiry,
        optional_data,
        composite,
    )

    return {
        "valid": structurally_valid
        and all(check["valid"] for check in required_checks),
        "structurally_valid": structurally_valid,
        "checks": checks,
    }


def correct_document_field(line2: str) -> tuple[str, list[dict]]:
    """Apply a unique checksum-supported correction to ambiguous OCR text."""
    normalized = line2.upper().replace(" ", "")[:44].ljust(44, "<")
    original = normalized[0:9]
    expected = normalized[9]

    if validate_check_digit(original, expected)["valid"]:
        return original, []

    ambiguous = {
        "0": "O",
        "O": "0",
        "1": "I",
        "I": "1",
        "2": "Z",
        "Z": "2",
        "5": "S",
        "S": "5",
        "6": "G",
        "G": "6",
        "8": "B",
        "B": "8",
    }
    candidates = []

    for index, character in enumerate(original):
        replacement = ambiguous.get(character)
        if replacement is None:
            continue
        candidate = original[:index] + replacement + original[index + 1 :]
        if validate_check_digit(candidate, expected)["valid"]:
            candidates.append((candidate, index, character, replacement))

    if len(candidates) != 1:
        return original, []

    candidate, index, source, replacement = candidates[0]
    return candidate, [
        {
            "field": "document_number",
            "position": index,
            "from": source,
            "to": replacement,
            "reason": "ICAO_CHECK_DIGIT",
        }
    ]
