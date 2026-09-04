import re
from datetime import datetime


# =========================================================
# DATE VALIDATION
# =========================================================

def validate_dates(identity):
    """
    Validate the logical relationship between DOB and expiry.
    """

    dob = identity.get("date_of_birth")
    expiry = identity.get("date_of_expiry")

    result = {
        "valid": True,
        "issues": []
    }

    if not dob:
        result["valid"] = False
        result["issues"].append("DOB_MISSING")

    if not expiry:
        result["valid"] = False
        result["issues"].append("EXPIRY_MISSING")

    if not dob or not expiry:
        return result

    try:
        dob_date = datetime.strptime(
            dob,
            "%Y-%m-%d"
        ).date()

        expiry_date = datetime.strptime(
            expiry,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        result["valid"] = False
        result["issues"].append("INVALID_DATE_FORMAT")

        return result

    # Expiry cannot be before DOB
    if expiry_date <= dob_date:

        result["valid"] = False

        result["issues"].append(
            "EXPIRY_BEFORE_DOB"
        )

    if dob_date > datetime.now().date():
        result["valid"] = False
        result["issues"].append(
            "DOB_IN_FUTURE"
        )

    return result


# =========================================================
# DOCUMENT NUMBER VALIDATION
# =========================================================

def validate_document_number(document_number):

    result = {
        "valid": True,
        "issues": []
    }

    if not document_number:

        result["valid"] = False

        result["issues"].append(
            "DOCUMENT_NUMBER_MISSING"
        )

        return result

    if not re.fullmatch(
        r"[A-Z0-9]{1,9}",
        document_number
    ):

        result["valid"] = False

        result["issues"].append(
            "INVALID_DOCUMENT_NUMBER_FORMAT"
        )

    return result


def validate_mrz(mrz):
    result = {
        "valid": True,
        "issues": []
    }

    if not mrz.get("required", True):
        return result

    if not mrz.get("detected", False):
        result["valid"] = False
        result["issues"].append("MRZ_MISSING")
        return result

    checksums = mrz.get("checksums")
    if checksums is not None and not checksums.get("valid", False):
        result["valid"] = False
        result["issues"].append("MRZ_CHECKSUM_FAILED")

    return result


def validate_visa(document):
    identity = document.get("identity", {})
    issues = []

    required = {
        "visa_number": "VISA_NUMBER_MISSING",
        "visa_type": "VISA_TYPE_MISSING",
        "entries": "VISA_ENTRIES_MISSING",
        "valid_from": "VISA_VALID_FROM_MISSING",
        "valid_until": "EXPIRY_MISSING",
        "stay_duration_days": "VISA_STAY_DURATION_MISSING",
    }
    checks = {}
    for field, issue in required.items():
        valid = bool(identity.get(field))
        checks[field] = {"valid": valid, "issues": [] if valid else [issue]}
        if not valid:
            issues.append(issue)

    valid_from = identity.get("valid_from")
    valid_until = identity.get("valid_until")
    dates_valid = True
    if valid_from and valid_until:
        try:
            dates_valid = datetime.strptime(valid_from, "%Y-%m-%d") <= datetime.strptime(
                valid_until, "%Y-%m-%d"
            )
        except ValueError:
            dates_valid = False
        if not dates_valid:
            issues.append("INVALID_VISA_VALIDITY_RANGE")

    expiry = validate_expiry(valid_until)
    if expiry["expired"]:
        issues.append("DOCUMENT_EXPIRED")

    total_checks = len(required) + 2
    passed_checks = sum(check["valid"] for check in checks.values())
    passed_checks += int(dates_valid)
    passed_checks += int(expiry["expired"] is False)

    checks["validity_range"] = {"valid": dates_valid, "issues": []}
    checks["expiry"] = expiry

    # These holder fields are optional because many visa stickers omit one or
    # more from the visible zone.  When present, still validate their format.
    passport_number = identity.get("passport_number")
    if passport_number:
        passport_valid = bool(re.fullmatch(r"[A-Z0-9]{5,12}", passport_number))
        checks["passport_number"] = {
            "valid": passport_valid,
            "issues": [] if passport_valid else ["INVALID_PASSPORT_NUMBER_FORMAT"],
        }
        total_checks += 1
        passed_checks += int(passport_valid)
        if not passport_valid:
            issues.append("INVALID_PASSPORT_NUMBER_FORMAT")

    date_of_birth = identity.get("date_of_birth")
    if date_of_birth:
        try:
            birth_valid = datetime.strptime(date_of_birth, "%Y-%m-%d").date() <= datetime.now().date()
        except ValueError:
            birth_valid = False
        checks["date_of_birth"] = {
            "valid": birth_valid,
            "issues": [] if birth_valid else ["DOB_MISSING_OR_INVALID"],
        }
        total_checks += 1
        passed_checks += int(birth_valid)
        if not birth_valid:
            issues.append("DOB_MISSING_OR_INVALID")

    return {
        "validation_score": round(passed_checks / total_checks * 100, 2),
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "issues": list(dict.fromkeys(issues)),
        "checks": checks,
    }


def validate_aadhaar(document):
    try:
        from .aadhaar import verhoeff_valid
    except ImportError:  # Support running analyzer.py as a script.
        from aadhaar import verhoeff_valid

    identity = document.get("identity", {})
    issues = []
    checks = {}

    def add_check(name, valid, issue):
        checks[name] = {"valid": bool(valid), "issues": [] if valid else [issue]}
        if not valid:
            issues.append(issue)

    number = str(identity.get("document_number") or "")
    masked = bool(identity.get("aadhaar_masked"))
    number_format_valid = bool(
        re.fullmatch(r"\d{4}", number) if masked else re.fullmatch(r"\d{12}", number)
    )
    add_check("document_number", number_format_valid, "AADHAAR_NUMBER_MISSING_OR_INVALID")

    checksum_valid = None if masked or not number_format_valid else verhoeff_valid(number)
    checks["checksum"] = {
        "valid": checksum_valid,
        "not_applicable": masked,
        "issues": [] if checksum_valid is not False else ["INVALID_AADHAAR_CHECKSUM"],
    }
    if checksum_valid is False:
        issues.append("INVALID_AADHAAR_CHECKSUM")

    add_check("name", identity.get("name"), "NAME_MISSING")

    birth = str(identity.get("date_of_birth") or "")
    birth_valid = False
    if re.fullmatch(r"\d{4}", birth):
        birth_valid = 1900 <= int(birth) <= datetime.now().year
    else:
        try:
            parsed_birth = datetime.strptime(birth, "%Y-%m-%d").date()
            birth_valid = parsed_birth <= datetime.now().date()
        except ValueError:
            pass
    add_check("date_of_birth", birth_valid, "DOB_MISSING_OR_INVALID")
    add_check("sex", identity.get("sex") in {"M", "F", "X"}, "SEX_MISSING_OR_INVALID")

    issuer_verification = document.get("issuer_verification")
    if issuer_verification is not None:
        add_check(
            "uidai_signature",
            issuer_verification.get("provider") == "UIDAI"
            and issuer_verification.get("signature_valid") is True,
            "UIDAI_SIGNATURE_INVALID",
        )

    # Masked Aadhaar cannot be checksum-validated, so score only applicable checks.
    applicable = [check for check in checks.values() if not check.get("not_applicable")]
    passed = sum(check["valid"] is True for check in applicable)
    return {
        "validation_score": round(passed / len(applicable) * 100, 2),
        "passed_checks": passed,
        "total_checks": len(applicable),
        "issues": issues,
        "checks": checks,
    }


def validate_generic_document(document):
    """Validate common fields without assuming one country's card template."""
    document_type = document.get("document_type")
    identity = document.get("identity", {})
    requirements = {
        "national_id": {
            "name": "NAME_MISSING",
            "document_number": "DOCUMENT_NUMBER_MISSING",
            "date_of_birth": "DOB_MISSING",
        },
        "driving_license": {
            "name": "NAME_MISSING",
            "document_number": "DOCUMENT_NUMBER_MISSING",
            "date_of_birth": "DOB_MISSING",
            "date_of_expiry": "EXPIRY_MISSING",
        },
        "permit": {
            "name": "NAME_MISSING",
            "document_number": "DOCUMENT_NUMBER_MISSING",
            "date_of_expiry": "EXPIRY_MISSING",
            "permit_type": "PERMIT_TYPE_MISSING",
        },
    }[document_type]

    checks = {}
    issues = []

    def add_check(name, valid, issue=None, **details):
        check_issues = [] if valid or not issue else [issue]
        checks[name] = {"valid": bool(valid), "issues": check_issues, **details}
        issues.extend(check_issues)

    for field, issue in requirements.items():
        add_check(field, bool(identity.get(field)), issue)

    number = str(identity.get("document_number") or "")
    number_format_valid = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9./-]{2,31}", number))
    if number:
        add_check(
            "document_number_format",
            number_format_valid,
            "INVALID_DOCUMENT_NUMBER_FORMAT",
        )

    parsed_dates = {}
    for field in ("date_of_birth", "date_of_issue", "valid_from", "date_of_expiry"):
        value = identity.get(field)
        if not value:
            continue
        try:
            parsed_dates[field] = datetime.strptime(value, "%Y-%m-%d").date()
            add_check(f"{field}_format", True)
        except ValueError:
            add_check(f"{field}_format", False, "INVALID_DATE_FORMAT")

    today = datetime.now().date()
    dob = parsed_dates.get("date_of_birth")
    issued = parsed_dates.get("date_of_issue") or parsed_dates.get("valid_from")
    expiry = parsed_dates.get("date_of_expiry")
    if dob:
        add_check("birth_not_future", dob <= today, "DOB_IN_FUTURE")
    if dob and issued:
        add_check("issue_after_birth", issued > dob, "ISSUE_BEFORE_DOB")
    if issued and expiry:
        add_check("validity_range", expiry >= issued, "INVALID_VALIDITY_RANGE")
    if dob and expiry:
        add_check("expiry_after_birth", expiry > dob, "EXPIRY_BEFORE_DOB")

    if expiry:
        expiry_result = validate_expiry(identity.get("date_of_expiry"))
        expiry_result["valid"] = expiry_result["expired"] is False
        expiry_result["issues"] = (
            [] if expiry_result["valid"] else ["DOCUMENT_EXPIRED"]
        )
        checks["expiry"] = expiry_result
        if expiry_result["expired"]:
            issues.append("DOCUMENT_EXPIRED")

    applicable = list(checks.values())
    passed = sum(check.get("valid") is True for check in applicable)
    return {
        "validation_score": round(passed / len(applicable) * 100, 2)
        if applicable else 0.0,
        "passed_checks": passed,
        "total_checks": len(applicable),
        "issues": list(dict.fromkeys(issues)),
        "checks": checks,
        "validation_profile": "GENERIC_VISIBLE_ZONE",
        "issuer_authenticated": False,
    }


# =========================================================
# NATIONALITY VALIDATION
# =========================================================

def validate_nationality(nationality):

    result = {
        "valid": True,
        "issues": []
    }

    if not nationality:

        result["valid"] = False

        result["issues"].append(
            "NATIONALITY_MISSING"
        )

        return result

    if not re.fullmatch(
        r"[A-Z]{3}",
        nationality
    ):

        result["valid"] = False

        result["issues"].append(
            "INVALID_NATIONALITY_CODE"
        )

    return result


# =========================================================
# SEX VALIDATION
# =========================================================

def validate_sex(sex):

    result = {
        "valid": True,
        "issues": []
    }

    if not sex:

        result["valid"] = False

        result["issues"].append(
            "SEX_MISSING"
        )

        return result

    if sex not in {"M", "F"}:

        result["valid"] = False

        result["issues"].append(
            "INVALID_SEX"
        )

    return result


# =========================================================
# EXPIRY STATUS
# =========================================================

def validate_expiry(expiry):

    if not expiry:

        return {
            "status": "UNKNOWN",
            "expired": None,
            "days_remaining": None
        }

    try:

        expiry_date = datetime.strptime(
            expiry,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        return {
            "status": "UNKNOWN",
            "expired": None,
            "days_remaining": None
        }

    today = datetime.now().date()

    days_remaining = (
        expiry_date - today
    ).days

    if days_remaining < 0:

        return {
            "status": "EXPIRED",
            "expired": True,
            "days_remaining": days_remaining
        }

    if days_remaining <= 180:

        return {
            "status": "EXPIRING_SOON",
            "expired": False,
            "days_remaining": days_remaining
        }

    return {
        "status": "VALID",
        "expired": False,
        "days_remaining": days_remaining
    }


# =========================================================
# COMPLETE VALIDATION
# =========================================================

def validate_document(document):

    if document.get("document_type") == "aadhaar":
        return validate_aadhaar(document)

    if document.get("document_type") == "visa":
        return validate_visa(document)

    if document.get("document_type") in {
        "national_id",
        "driving_license",
        "permit",
    }:
        return validate_generic_document(document)

    identity = document.get(
        "identity",
        {}
    )

    document_number = identity.get(
        "document_number"
    )

    nationality = identity.get(
        "nationality"
    )

    sex = identity.get(
        "sex"
    )

    # -----------------------------------------------------
    # Individual checks
    # -----------------------------------------------------

    document_number_check = (
        validate_document_number(
            document_number
        )
    )

    nationality_check = (
        validate_nationality(
            nationality
        )
    )

    sex_check = (
        validate_sex(
            sex
        )
    )

    date_check = (
        validate_dates(
            identity
        )
    )

    expiry_check = (
        validate_expiry(
            identity.get(
                "date_of_expiry"
            )
        )
    )

    mrz_check = validate_mrz(
        document.get("mrz", {})
    )

    # -----------------------------------------------------
    # Collect issues
    # -----------------------------------------------------

    issues = []

    checks = [
        document_number_check,
        nationality_check,
        sex_check,
        date_check,
        mrz_check
    ]

    for check in checks:

        issues.extend(
            check["issues"]
        )

    if expiry_check["expired"]:

        issues.append(
            "DOCUMENT_EXPIRED"
        )

    # -----------------------------------------------------
    # Calculate validation score
    # -----------------------------------------------------

    total_checks = 6

    passed_checks = 0

    if document_number_check["valid"]:
        passed_checks += 1

    if nationality_check["valid"]:
        passed_checks += 1

    if sex_check["valid"]:
        passed_checks += 1

    if date_check["valid"]:
        passed_checks += 1

    if expiry_check["expired"] is False:
        passed_checks += 1

    if mrz_check["valid"]:
        passed_checks += 1

    validation_score = (
        passed_checks /
        total_checks
    ) * 100

    return {

        "validation_score":
            round(
                validation_score,
                2
            ),

        "passed_checks":
            passed_checks,

        "total_checks":
            total_checks,

        "issues":
            issues,

        "checks": {

            "document_number":
                document_number_check,

            "nationality":
                nationality_check,

            "sex":
                sex_check,

            "dates":
                date_check,

            "expiry":
                expiry_check,

            "mrz":
                mrz_check
        }
    }
