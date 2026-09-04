import json
from pathlib import Path
from datetime import datetime

if __package__:
    from .aadhaar import analyze_aadhaar
    from .authenticity import assess_authenticity
    from .cross_validator import cross_validate_documents
    from .document_classifier import classify_document
    from .generic_document import analyze_generic_document
    from .mrz import analyze_mrz
    from .passport import analyze_passport
    from .risk_engine import calculate_risk
    from .validation import validate_document
    from .visa import analyze_visa
else:
    from aadhaar import analyze_aadhaar
    from authenticity import assess_authenticity
    from cross_validator import cross_validate_documents
    from document_classifier import classify_document
    from generic_document import analyze_generic_document
    from mrz import analyze_mrz
    from passport import analyze_passport
    from risk_engine import calculate_risk
    from validation import validate_document
    from visa import analyze_visa


PROJECT_ROOT = Path(__file__).resolve().parents[2]

OCR_FILE = (
    PROJECT_ROOT
    / "datasets"
    / "processed"
    / "ocr_text.json"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "datasets"
    / "processed"
    / "document_analysis.json"
)


def calculate_expiry_status(expiry_date):
    """Determine whether a document is valid or expired."""

    if not expiry_date:
        return {
            "status": "UNKNOWN",
            "days_remaining": None
        }

    try:
        expiry = datetime.strptime(
            expiry_date,
            "%Y-%m-%d"
        ).date()

    except ValueError:
        return {
            "status": "UNKNOWN",
            "days_remaining": None
        }

    today = datetime.now().date()

    days_remaining = (
        expiry - today
    ).days

    if days_remaining < 0:

        return {
            "status": "EXPIRED",
            "days_remaining": days_remaining
        }

    elif days_remaining <= 180:

        return {
            "status": "EXPIRING_SOON",
            "days_remaining": days_remaining
        }

    else:

        return {
            "status": "VALID",
            "days_remaining": days_remaining
        }


#def build_document_record(ocr_items):
#
#    # --------------------------------------------------
#    # OCR analysis
#    # --------------------------------------------------
#
#    passport_data = analyze_passport(
#        ocr_items
#    )
#
#    # --------------------------------------------------
#    # MRZ analysis
#    # --------------------------------------------------
#
#    mrz_data = analyze_mrz(
#        ocr_items
#    )
#
#    records = []
#
#    # --------------------------------------------------
#    # Build records from MRZ
#    # --------------------------------------------------
#
#    for mrz_record in mrz_data["records"]:
#
#        expiry_status = calculate_expiry_status(
#            mrz_record.get("date_of_expiry")
#        )
#
#    # --------------------------------------------------
#    # Cross validate OCR against MRZ
#    # --------------------------------------------------
#
#    cross_validation_results = cross_validate_documents(
#        records,
#        ocr_items
#    )
#
#    for record, cross_validation in zip(
#        records,
#        cross_validation_results
#    ):
#
#        record["cross_validation"] = cross_validation
#
#        record = {
#
#            "document_type": "passport",
#
#            "identity": {
#
#                "document_number":
#                    mrz_record.get(
#                        "document_number"
#                    ),
#
#                "nationality":
#                    mrz_record.get(
#                        "nationality"
#                    ),
#
#                "date_of_birth":
#                    mrz_record.get(
#                        "date_of_birth"
#                    ),
#
#                "sex":
#                    mrz_record.get(
#                        "sex"
#                    ),
#
#                "date_of_expiry":
#                    mrz_record.get(
#                        "date_of_expiry"
#                    )
#            },
#
#            "mrz": {
#
#                "detected": True,
#
#                "raw":
#                    mrz_record.get(
#                        "raw"
#                    )
#            },
#
#            "expiry": expiry_status,
#
#            "validation": {
#
#                "document_number_present":
#                    bool(
#                        mrz_record.get(
#                            "document_number"
#                        )
#                    ),
#
#                "nationality_present":
#                    bool(
#                        mrz_record.get(
#                            "nationality"
#                        )
#                    ),
#
#                "dob_present":
#                    bool(
#                        mrz_record.get(
#                            "date_of_birth"
#                        )
#                    ),
#
#                "expiry_present":
#                    bool(
#                        mrz_record.get(
#                            "date_of_expiry"
#                        )
#                    )
#            }
#        }
#
#        validation = validate_document(record)
#
#        record["validation"] = validation
#
#        risk = calculate_risk(record)
#
#        record["risk"] = risk
#
#        records.append(record)
#
#    # --------------------------------------------------
#    # If no MRZ was found
#    # --------------------------------------------------
#
#    if not records:
#
#        records.append({
#
#            "document_type":
#                passport_data.get(
#                    "document_type"
#                ),
#
#            "identity":
#                passport_data.get(
#                    "fields"
#                ),
#
#            "mrz": {
#
#                "detected": False,
#
#                "raw": None
#            },
#
#            "expiry": {
#
#                "status": "UNKNOWN",
#
#                "days_remaining": None
#            },
#
#            "validation": {
#
#                "document_number_present":
#                    bool(
#                        passport_data[
#                            "fields"
#                        ].get(
#                            "passport_number"
#                        )
#                    ),
#
#                "nationality_present":
#                    bool(
#                        passport_data[
#                            "fields"
#                        ].get(
#                            "nationality"
#                        )
#                    )
#            }
#        })
#
#    return {
#
#        "analysis_timestamp":
#            datetime.now().isoformat(),
#
#        "document_count":
#            len(records),
#
#        "documents":
#            records
#    }


def build_document_record(ocr_items, image_path=None, forensic_result=None):

    # --------------------------------------------------
    # OCR & MRZ analysis
    # --------------------------------------------------
    classification = classify_document(ocr_items)
    passport_data = analyze_passport(ocr_items)
    mrz_data = analyze_mrz(ocr_items)

    records = []

    if classification["document_type"] == "aadhaar":
        aadhaar_data = analyze_aadhaar(ocr_items)
        fields = aadhaar_data["fields"]
        aadhaar_record = {
            "document_type": "aadhaar",
            "identity": fields,
            "mrz": {"detected": False, "required": False, "raw": None},
            "expiry": {
                "status": "NOT_APPLICABLE",
                "days_remaining": None,
            },
            "extraction": {
                "confidence": aadhaar_data["extraction_confidence"],
                "missing_fields": aadhaar_data["missing_fields"],
                "ocr_corrections": aadhaar_data["ocr_corrections"],
            },
        }
        aadhaar_record["validation"] = validate_document(aadhaar_record)
        records.append(aadhaar_record)

    elif classification["document_type"] == "visa":
        visa_data = analyze_visa(ocr_items)
        fields = visa_data["fields"]
        visa_record = {
            "document_type": "visa",
            "identity": fields,
            "mrz": {"detected": False, "required": False, "raw": None},
            "expiry": calculate_expiry_status(fields.get("valid_until")),
            "extraction": {
                "confidence": visa_data["extraction_confidence"],
                "missing_fields": visa_data["missing_fields"],
            },
        }
        visa_record["validation"] = validate_document(visa_record)
        records.append(visa_record)

    elif classification["document_type"] in {
        "national_id",
        "driving_license",
        "permit",
    }:
        generic_data = analyze_generic_document(
            ocr_items,
            classification["document_type"],
        )
        fields = generic_data["fields"]
        generic_record = {
            "document_type": classification["document_type"],
            "identity": fields,
            "mrz": {"detected": False, "required": False, "raw": None},
            "expiry": calculate_expiry_status(fields.get("date_of_expiry")),
            "extraction": {
                "supported": True,
                "confidence": generic_data["extraction_confidence"],
                "missing_fields": generic_data["missing_fields"],
                "field_provenance": generic_data["field_provenance"],
                "limitations": generic_data["limitations"],
            },
        }
        generic_record["validation"] = validate_document(generic_record)
        records.append(generic_record)

    elif classification["document_type"] == "unknown":
        records.append({
            "document_type": "unknown",
            "identity": {},
            "mrz": {"detected": False, "required": False, "raw": None},
            "expiry": {"status": "UNKNOWN", "days_remaining": None},
            "extraction": {
                "supported": False,
                "confidence": 0.0,
                "missing_fields": [],
            },
            "validation": {
                "validation_score": 0.0,
                "passed_checks": 0,
                "total_checks": 1,
                "issues": ["UNSUPPORTED_DOCUMENT_TYPE"],
                "checks": {
                    "document_type": {
                        "valid": False,
                        "issues": ["UNSUPPORTED_DOCUMENT_TYPE"],
                    }
                },
            },
        })

    # --------------------------------------------------
    # Build records from MRZ
    # --------------------------------------------------
    for mrz_record in (
        [] if records else mrz_data.get("records", [])
    ):

        visual_fields = passport_data.get("fields", {})
        def mrz_or_visual(field, visual_field=None):
            return mrz_record.get(field) or visual_fields.get(visual_field or field)

        expiry_status = calculate_expiry_status(
            mrz_or_visual("date_of_expiry")
        )

        record = {
            "document_type": "passport",
            "visual_zone": {
                "fields": visual_fields,
                "confidence": passport_data.get("confidence", {}),
            },
            "identity": {
                "name": (
                    mrz_record.get("name")
                    or passport_data.get("fields", {}).get("name")
                ),
                "issuing_state": mrz_record.get("issuing_state"),
                "document_number": mrz_or_visual("document_number"),
                "nationality": mrz_or_visual("nationality"),
                "date_of_birth": mrz_or_visual("date_of_birth"),
                "sex": mrz_or_visual("sex"),
                "date_of_expiry": mrz_or_visual("date_of_expiry"),
                "date_of_issue": visual_fields.get("date_of_issue"),
                "place_of_birth": visual_fields.get("place_of_birth"),
                "place_of_issue": visual_fields.get("place_of_issue"),
                "issuing_authority": visual_fields.get("issuing_authority"),
            },
            "mrz": {
                "detected": True,
                "raw": mrz_record.get("raw"),
                "checksums": mrz_record.get("checksums"),
                "ocr_corrections": mrz_record.get("ocr_corrections", [])
            },
            "expiry": expiry_status,
            "validation": {
                "document_number_present": bool(mrz_record.get("document_number")),
                "nationality_present": bool(mrz_record.get("nationality")),
                "dob_present": bool(mrz_record.get("date_of_birth")),
                "expiry_present": bool(mrz_record.get("date_of_expiry"))
            }
        }

        # Run validation on the record. Risk is calculated after
        # cross-validation and image forensics are available.
        record["validation"] = validate_document(record)

        records.append(record)

    # --------------------------------------------------
    # Fallback: If no MRZ was found
    # --------------------------------------------------
    if not records:
        fallback_record = {
            "document_type": passport_data.get("document_type", "passport"),
            "identity": passport_data.get("fields", {}),
            "mrz": {
                "detected": False,
                "raw": None
            },
            "expiry": calculate_expiry_status(
                passport_data.get("fields", {}).get("date_of_expiry")
            ),
        }
        fallback_record["validation"] = validate_document(fallback_record)
        records.append(fallback_record)

    # --------------------------------------------------
    # Cross-validation, optional forensics, and final risk
    # --------------------------------------------------
    cross_validation_results = cross_validate_documents(
        records,
        ocr_items
    )

    if forensic_result is None and image_path is not None:
        from ..image_forensics.forensic_engine import analyze_image_forensics

        forensic_result = analyze_image_forensics(image_path)

    for record, cross_val in zip(records, cross_validation_results):
        record["cross_validation"] = cross_val
        if forensic_result is not None:
            record["forensics"] = forensic_result
        record["authenticity"] = assess_authenticity(record)
        record["risk"] = calculate_risk(record)

    return {
        "analysis_timestamp": datetime.now().isoformat(),
        "classification": classification,
        "document_count": len(records),
        "documents": records
    }


def main():

    print("=" * 60)
    print("AI DOCUMENT ANALYSIS ENGINE")
    print("=" * 60)

    if not OCR_FILE.exists():

        print()
        print("ERROR: OCR output not found.")
        print(OCR_FILE)

        return

    # --------------------------------------------------
    # Load OCR
    # --------------------------------------------------

    with open(
        OCR_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        ocr_items = json.load(file)

    print(
        f"OCR entries: {len(ocr_items)}"
    )

    print()

    # --------------------------------------------------
    # Analyze
    # --------------------------------------------------

    result = build_document_record(
        ocr_items
    )

    # --------------------------------------------------
    # Save
    # --------------------------------------------------

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=4,
            ensure_ascii=False
        )

    # --------------------------------------------------
    # Display
    # --------------------------------------------------

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False
        )
    )

    print()
    print("=" * 60)
    print("DOCUMENT ANALYSIS COMPLETE")
    print("=" * 60)

    print()
    print(
        f"Saved to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
