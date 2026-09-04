"""Deterministic synthetic inputs shared by integration tests."""

from ai.document_analysis.icao import calculate_check_digit


def _ocr_item(text, y):
    return {
        "text": text,
        "confidence": 0.99,
        "bbox": [[0, y], [100, y], [100, y + 10], [0, y + 10]],
    }


def build_td3_line2(
    document_field="A1234567<",
    nationality="IND",
    date_of_birth="900101",
    sex="F",
    date_of_expiry="301231",
    optional_data="<<<<<<<<<<<<<<",
):
    document_check = calculate_check_digit(document_field)
    dob_check = calculate_check_digit(date_of_birth)
    expiry_check = calculate_check_digit(date_of_expiry)
    optional_check = calculate_check_digit(optional_data)
    body = (
        document_field
        + document_check
        + nationality
        + date_of_birth
        + dob_check
        + sex
        + date_of_expiry
        + expiry_check
        + optional_data
        + optional_check
    )
    composite_data = (
        document_field
        + document_check
        + date_of_birth
        + dob_check
        + date_of_expiry
        + expiry_check
        + optional_data
        + optional_check
    )
    return body + calculate_check_digit(composite_data)


def passport_ocr_items(tamper_mrz=False):
    line1 = "P<INDDOE<<JANE<ALICE".ljust(44, "<")
    line2 = build_td3_line2()
    if tamper_mrz:
        line2 = line2[:28] + "B" + line2[29:]

    lines = [
        "PASSPORT",
        "Name: JANE ALICE DOE",
        "Passport No: A1234567",
        "Nationality: IND",
        "Date of Birth: 01/01/1990",
        "Date of Expiry: 31/12/2030",
        "Sex: F",
        line1,
        line2,
    ]
    return [_ocr_item(text, index * 20) for index, text in enumerate(lines)]


def visa_ocr_items():
    lines = [
        "REPUBLIC VISA",
        "Visa Number: V1234567",
        "Visa Type: TOURIST",
        "Number of Entries: MULTIPLE",
        "Valid From: 01/01/2026",
        "Valid Until: 31/12/2027",
        "Duration of Stay: 90 Days",
    ]
    return [_ocr_item(text, index * 20) for index, text in enumerate(lines)]


def passing_face_result():
    return {
        "verification_passed": True,
        "face_match": True,
        "face_similarity": 0.61,
        "face_match_threshold": 0.40,
        "liveness_passed": True,
        "liveness_score": 1.0,
        "blink_detected": True,
        "head_turn_detected": True,
    }
