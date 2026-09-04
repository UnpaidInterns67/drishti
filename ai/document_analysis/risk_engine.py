from datetime import datetime


# =========================================================
# RISK WEIGHTS
# =========================================================

RISK_WEIGHTS = {

    "DOCUMENT_EXPIRED": 30,

    "DOCUMENT_NUMBER_MISSING": 20,

    "NATIONALITY_MISSING": 15,

    "DOB_MISSING": 15,

    "EXPIRY_MISSING": 15,

    "SEX_MISSING": 10,

    "INVALID_DOCUMENT_NUMBER_FORMAT": 25,

    "INVALID_NATIONALITY_CODE": 20,

    "INVALID_SEX": 20,

    "INVALID_DATE_FORMAT": 25,

    "DOB_IN_FUTURE": 50,

    "EXPIRY_BEFORE_DOB": 50,

    "UNUSUAL_DOCUMENT_AGE": 10,

    "MRZ_MISSING": 25,

    "MRZ_CHECKSUM_FAILED": 50,

    "FIELD_MISMATCH": 40,

    "POSSIBLE_TAMPERING": 60,

    "VISA_NUMBER_MISSING": 25,

    "VISA_TYPE_MISSING": 15,

    "VISA_ENTRIES_MISSING": 15,

    "VISA_VALID_FROM_MISSING": 15,

    "VISA_STAY_DURATION_MISSING": 15,

    "INVALID_VISA_VALIDITY_RANGE": 50,

    "AADHAAR_NUMBER_MISSING_OR_INVALID": 30,

    "INVALID_AADHAAR_CHECKSUM": 50,

    "UIDAI_SIGNATURE_INVALID": 100,

    "AADHAAR_FRONT_QR_MISMATCH": 100,

    "AADHAAR_PHOTO_QR_MISMATCH": 100,

    "AADHAAR_PHOTO_QR_INCONCLUSIVE": 35,

    "AADHAAR_FRONT_OCR_INCONCLUSIVE": 35,

    "NAME_MISSING": 20,

    "DOB_MISSING_OR_INVALID": 25,

    "SEX_MISSING_OR_INVALID": 15,

    "OCR_CORRECTION_UNVERIFIED": 25,

    "UNSUPPORTED_DOCUMENT_TYPE": 40,

    "PERMIT_TYPE_MISSING": 15,

    "ISSUE_BEFORE_DOB": 50,

    "INVALID_VALIDITY_RANGE": 50,

    "CAPTURE_QUALITY_INSUFFICIENT": 35,
}


# =========================================================
# RISK LEVEL
# =========================================================

def get_risk_level(score):

    if score >= 70:
        return "HIGH"

    if score >= 35:
        return "MEDIUM"

    return "LOW"


# =========================================================
# DECISION
# =========================================================

def get_decision(score):

    if score >= 70:
        return "FLAG"

    if score >= 35:
        return "REVIEW"

    return "PASS"


# =========================================================
# CALCULATE RISK
# =========================================================

def calculate_risk(document):

    validation = document.get(
        "validation",
        {}
    )

    issues = validation.get(
        "issues",
        []
    )

    score = 0

    reasons = []

    signals = []

    seen_signals = set()

    def add_signal(signal, signal_type, weight, reason, evidence=None):
        nonlocal score
        if signal in seen_signals:
            return
        seen_signals.add(signal)
        score += weight
        reasons.append(reason)
        item = {
            "type": signal_type,
            "signal": signal,
            "weight": weight
        }
        if evidence is not None:
            item["evidence"] = evidence
        signals.append(item)

    # -----------------------------------------------------
    # Validation issues
    # -----------------------------------------------------

    for issue in issues:

        weight = RISK_WEIGHTS.get(
            issue,
            10
        )

        add_signal(
            issue,
            "VALIDATION",
            weight,
            issue.replace("_", " ").title()
        )

    # -----------------------------------------------------
    # MRZ detection
    # -----------------------------------------------------

    mrz = document.get(
        "mrz",
        {}
    )

    if mrz.get("required", document.get("document_type") == "passport") and not mrz.get("detected", False):

        weight = RISK_WEIGHTS[
            "MRZ_MISSING"
        ]

        add_signal(
            "MRZ_MISSING",
            "MRZ",
            weight,
            "Machine readable zone not detected"
        )

    # A check digit can support an OCR suggestion, but it does not independently
    # verify the printed value or document. Never auto-approve a corrected
    # identity number without a second trusted source such as signed QR data.
    corrections = document.get("extraction", {}).get("ocr_corrections", [])
    unverified_corrections = [
        correction
        for correction in corrections
        if not correction.get("independently_verified", False)
    ]
    if unverified_corrections:
        add_signal(
            "OCR_CORRECTION_UNVERIFIED",
            "OCR_INTEGRITY",
            RISK_WEIGHTS["OCR_CORRECTION_UNVERIFIED"],
            "Checksum-supported OCR correction requires independent review",
            {"corrections": unverified_corrections},
        )

    # -----------------------------------------------------
    # OCR/MRZ cross-validation
    # -----------------------------------------------------

    cross_validation = document.get("cross_validation", {})
    mismatch_count = int(cross_validation.get("mismatches", 0) or 0)
    if mismatch_count:
        add_signal(
            "FIELD_MISMATCH",
            "CROSS_VALIDATION",
            RISK_WEIGHTS["FIELD_MISMATCH"],
            "Printed fields do not match MRZ data",
            {"mismatches": mismatch_count}
        )

    # -----------------------------------------------------
    # Image-forensic evidence
    # -----------------------------------------------------

    forensics = document.get("forensics", {})
    forensic_overall = forensics.get("overall", {})
    tampering_score = float(
        forensic_overall.get(
            "tampering_score",
            forensic_overall.get("score", 0),
        )
        or 0
    )

    if tampering_score >= 60:
        tampering_weight = RISK_WEIGHTS["POSSIBLE_TAMPERING"]
    elif tampering_score >= 35:
        tampering_weight = 35
    else:
        tampering_weight = 0

    if tampering_weight:
        add_signal(
            "POSSIBLE_TAMPERING",
            "IMAGE_FORENSICS",
            tampering_weight,
            "Image-forensic anomalies require review",
            {
                "tampering_score": round(tampering_score, 2),
                "signals": forensic_overall.get("signals", []),
            }
        )

    capture_quality = forensic_overall.get("capture_quality", {})
    strong_machine_evidence = bool(
        (document.get("mrz", {}).get("checksums") or {}).get("valid")
        or (document.get("issuer_verification") or {}).get("signature_valid") is True
    )
    if capture_quality.get("blocking") and not strong_machine_evidence:
        add_signal(
            "CAPTURE_QUALITY_INSUFFICIENT",
            "IMAGE_QUALITY",
            RISK_WEIGHTS["CAPTURE_QUALITY_INSUFFICIENT"],
            "Document should be recaptured before a fraud conclusion is made",
            capture_quality,
        )

    # -----------------------------------------------------
    # Cap risk score
    # -----------------------------------------------------

    score = min(
        score,
        100
    )

    # -----------------------------------------------------
    # Final result
    # -----------------------------------------------------

    return {

        "risk_score": score,

        "risk_level":
            get_risk_level(score),

        "decision":
            get_decision(score),

        "reasons":
            reasons,

        "signals":
            signals
    }
