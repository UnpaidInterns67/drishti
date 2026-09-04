#import re
#from datetime import datetime
#
#
## ---------------------------------------------------------
## Detect MRZ-like lines
## ---------------------------------------------------------
#
#def is_mrz_line(text: str) -> bool:
#    if not text:
#        return False
#
#    text = text.strip().upper().replace(" ", "")
#
#    if len(text) < 30:
#        return False
#
#    if not re.fullmatch(r"^[A-Z0-9<]+$", text):
#        return False
#
#    # Real MRZ lines are dense with '<' fillers relative to length —
#    # use this as a generic acceptance signal instead of requiring
#    # a specific prefix/pattern.
#    if "<" in text:
#        return True
#
#    # Fallback: still accept synthetic format even without '<'
#    if re.search(r"[A-Z0-9]{8}[A-Z]{3}\d{8}[MF]\d{8}", text):
#        return True
#
#    return False
#
#
## ---------------------------------------------------------
## Extract MRZ lines
## ---------------------------------------------------------
#
#def extract_mrz_lines(ocr_items):
#    # sort top-to-bottom using bbox if available
#    sorted_items = sorted(
#        ocr_items,
#        key=lambda item: item.get("bbox", [[0, 0]])[0][1]  # y of top-left point
#    )
#    mrz_lines = []
#    for item in sorted_items:
#        text = item.get("text", "").strip().upper()
#        if is_mrz_line(text):
#            mrz_lines.append(text.replace(" ", ""))
#    return mrz_lines
#
#
## ---------------------------------------------------------
## Parse synthetic MRZ format
## ---------------------------------------------------------
#
#def parse_synthetic_mrz(line: str):
#    line = line.replace(" ", "").upper()
#
#    pattern = (
#        r"^"
#        r"(.{9})"       # Document number — 9 chars (matches this dataset)
#        r"([A-Z]{3})"   # Nationality
#        r"(\d{8})"      # DOB (DDMMYYYY)
#        r"([MF])"       # Sex
#        r"(\d{8})"      # Expiry (DDMMYYYY)
#    )
#
#    match = re.match(pattern, line)
#    if not match:
#        return None
#
#    document_number = match.group(1)
#    nationality = match.group(2)
#
#    dob_raw = match.group(3)
#    sex = match.group(4)
#    expiry_raw = match.group(5)
#
#    try:
#
#        dob = datetime.strptime(
#            dob_raw,
#            "%d%m%Y"
#        ).strftime("%Y-%m-%d")
#
#    except ValueError:
#
#        dob = None
#
#    try:
#
#        expiry = datetime.strptime(
#            expiry_raw,
#            "%d%m%Y"
#        ).strftime("%Y-%m-%d")
#
#    except ValueError:
#
#        expiry = None
#
#    return {
#        "document_number": document_number,
#        "nationality": nationality,
#        "date_of_birth": dob,
#        "sex": sex,
#        "date_of_expiry": expiry,
#        "raw": line
#    }
#
#def parse_standard_mrz(line1: str, line2: str):
#    """
#    Parse a standard ICAO TD3 passport MRZ.
#
#    A valid TD3 passport MRZ consists of:
#
#    Line 1:
#        P<COUNTRYNAME...
#
#    Line 2:
#        DOCUMENT_NUMBER + CHECK_DIGIT
#        NATIONALITY
#        DOB + CHECK_DIGIT
#        SEX
#        EXPIRY + CHECK_DIGIT
#        ...
#
#    We perform structural validation before extracting fields.
#    """
#
#    line1 = line1.replace(" ", "").upper()
#    line2 = line2.replace(" ", "").upper()
#
#    # First line must start with P<
#    if not line1.startswith("P<"):
#        return None
#
#    # Standard TD3 line 2 is normally 44 characters.
#    # OCR can occasionally lose characters, so we allow
#    # a small amount of variation.
#    if len(line2) < 30:
#        return None
#
#    # -----------------------------------------------------
#    # IMPORTANT:
#    # The second line must contain a real MRZ structure.
#    #
#    # Position:
#    # 0-8   passport/document number
#    # 9     document number check digit
#    # 10-12 nationality
#    # 13-18 DOB
#    # 19    DOB check digit
#    # 20    sex
#    # 21-26 expiry
#    # 27    expiry check digit
#    # -----------------------------------------------------
#
#    # Nationality must be exactly 3 letters
#    nationality = line2[10:13]
#
#    if not re.fullmatch(r"[A-Z]{3}", nationality):
#        return None
#
#    # Date fields must contain six digits
#    dob_raw = line2[13:19]
#    expiry_raw = line2[21:27]
#
#    if not re.fullmatch(r"\d{6}", dob_raw):
#        return None
#
#    if not re.fullmatch(r"\d{6}", expiry_raw):
#        return None
#
#    # Sex must be M, F or <
#    sex = line2[20]
#
#    if sex not in {"M", "F", "<"}:
#        return None
#
#    # Document number
#    document_number = line2[0:9].replace("<", "")
#
#    # Convert dates
#    try:
#
#        dob = datetime.strptime(
#            dob_raw,
#            "%y%m%d"
#        ).strftime("%Y-%m-%d")
#
#    except ValueError:
#
#        dob = None
#
#    try:
#
#        expiry = datetime.strptime(
#            expiry_raw,
#            "%y%m%d"
#        ).strftime("%Y-%m-%d")
#
#    except ValueError:
#
#        expiry = None
#
#    return {
#        "document_number": document_number,
#        "nationality": nationality,
#        "date_of_birth": dob,
#        "sex": None if sex == "<" else sex,
#        "date_of_expiry": expiry,
#        "raw": [
#            line1,
#            line2
#        ]
#    }
#
#
## ---------------------------------------------------------
## Main MRZ analysis
## ---------------------------------------------------------
#
#def analyze_mrz(ocr_items):
#
#    lines = extract_mrz_lines(ocr_items)
#
#    results = []
#
#    i = 0
#
#    while i < len(lines):
#
#        line = lines[i]
#
#        # Synthetic format
#        synthetic = parse_synthetic_mrz(line)
#
#        if synthetic:
#
#            results.append(synthetic)
#
#            i += 1
#
#            continue
#
#        # Standard passport MRZ
#        if line.startswith("P<") and i + 1 < len(lines):
#
#            standard = parse_standard_mrz(
#                line,
#                lines[i + 1]
#            )
#
#            if standard:
#
#                results.append(standard)
#
#                i += 2
#
#                continue
#
#        i += 1
#
#    return {
#        "mrz_detected": len(results) > 0,
#        "lines_detected": lines,
#        "records": results
#    }



import json
import re
import sys
from datetime import datetime
from pathlib import Path

if __package__:
    from .icao import correct_document_field, validate_td3_line2
else:
    from icao import correct_document_field, validate_td3_line2

# ---------------------------------------------------------
# Clean OCR text noise before validation
# ---------------------------------------------------------

def clean_ocr_mrz(text: str) -> str:
    """Normalizes OCR misreadings of MRZ filler characters."""
    if not text:
        return ""
    text = text.upper().strip().replace(" ", "")
    text = re.sub(r"[«\(\[\{\\\|]", "<", text)
    return text


def is_mrz_line(text: str) -> bool:
    """
    Determine whether OCR text is likely to be an MRZ line.
    """

    if not text:
        return False

    text = clean_ocr_mrz(text)

    # MRZ should be reasonably long
    if len(text) < 29:
        return False

    # Only MRZ characters
    if not re.fullmatch(
        r"^[A-Z0-9<]+$",
        text
    ):
        return False

    # -----------------------------------------------------
    # Passport TD3 first line
    # -----------------------------------------------------

    if text.startswith("P<"):
        return True

    # -----------------------------------------------------
    # Standard passport TD3 second line.
    #
    # Look for:
    #
    # document number
    # nationality
    # DOB
    # sex
    # expiry
    # -----------------------------------------------------

    standard_pattern = (
        r"^[A-Z0-9<]{9}"
        r"[0-9<]"
        r"[A-Z]{3}"
        r"\d{6}"
        r"[0-9<]"
        r"[MF<]"
        r"\d{6}"
        r"[0-9<]"
    )

    if re.match(
        standard_pattern,
        text
    ):
        return True

    # OCR commonly confuses letters and digits in fixed-position TD3 fields
    # (for example IND -> 1ND).  Do not discard an otherwise MRZ-shaped lower
    # line before the position-aware normalizer gets a chance to repair it.
    if len(text) >= 35 and "<" in text and re.fullmatch(r"[A-Z0-9<]+", text):
        return True

    # -----------------------------------------------------
    # Synthetic format used by our dataset
    # -----------------------------------------------------

    synthetic_pattern = (
        r"^[A-Z0-9<]{9}"
        r"[A-Z]{3}"
        r"\d{8}"
        r"[MF]"
        r"\d{8}"
    )

    if re.match(
        synthetic_pattern,
        text
    ):
        return True

    return False


# ---------------------------------------------------------
# Extract & spatially reconstruct MRZ lines
# ---------------------------------------------------------

def extract_mrz_lines(ocr_items):
    sorted_items = sorted(
        ocr_items,
        key=lambda item: item.get("bbox", [[0, 0]])[0][1]
    )

    mrz_lines = []
    for item in sorted_items:
        text = clean_ocr_mrz(item.get("text", ""))
        if is_mrz_line(text):
            mrz_lines.append(text)

    return mrz_lines


# ---------------------------------------------------------
# Robust Date Parsing (Handles zero-padded dummy dates)
# ---------------------------------------------------------

# ---------------------------------------------------------
# Robust Date Parsing (Handles zero-padded & dirty OCR dates)
# ---------------------------------------------------------

def parse_mrz_date(date_str: str, is_expiry: bool = False) -> str:
    """
    Parses YYMMDD date strings to YYYY-MM-DD.
    Safely handles common OCR noise. Invalid/placeholder dates remain unknown;
    they must not be silently converted into real identity data.
    """
    if not date_str or len(date_str) != 6:
        return None

    # Replace common OCR misreads in numeric date fields
    cleaned_date = date_str.upper().replace("O", "0").replace("I", "1").replace("Z", "2")

    # Reject non-numeric strings safely instead of crashing
    if not cleaned_date.isdigit():
        return None

    yy, mm, dd = cleaned_date[:2], cleaned_date[2:4], cleaned_date[4:6]

    current_yy = int(datetime.now().strftime("%y"))

    if is_expiry:
        century = "20"
    else:
        try:
            century = "19" if int(yy) > current_yy else "20"
        except ValueError:
            return None

    try:
        dt = datetime.strptime(f"{century}{yy}{mm}{dd}", "%Y%m%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def normalize_td3_line2(line2: str) -> tuple[str, list[dict]]:
    """Normalize OCR confusions only where TD3 positions constrain the type."""
    normalized = clean_ocr_mrz(line2)[:44].ljust(44, "<")
    characters = list(normalized)
    corrections = []
    alpha_map = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
    digit_map = {"O": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}

    def correct_positions(positions, mapping, field):
        for position in positions:
            source = characters[position]
            replacement = mapping.get(source)
            if replacement is None:
                continue
            characters[position] = replacement
            corrections.append({
                "field": field,
                "position": position,
                "from": source,
                "to": replacement,
                "reason": "TD3_POSITION_TYPE",
            })

    correct_positions(range(10, 13), alpha_map, "nationality")
    correct_positions((*range(13, 20), *range(21, 28), 42, 43), digit_map, "numeric_field")
    return "".join(characters), corrections


# ---------------------------------------------------------
# Parse synthetic MRZ format
# ---------------------------------------------------------

def parse_synthetic_mrz(line: str):
    line = clean_ocr_mrz(line)

    pattern = (
        r"^"
        r"(.{9})"       # Document number
        r"([A-Z]{3})"   # Nationality
        r"(\d{8})"      # DOB (DDMMYYYY)
        r"([MF])"       # Sex
        r"(\d{8})"      # Expiry (DDMMYYYY)
    )

    match = re.match(pattern, line)
    if not match:
        return None

    document_number = match.group(1)
    nationality = match.group(2)
    dob_raw = match.group(3)
    sex = match.group(4)
    expiry_raw = match.group(5)

    try:
        dob = datetime.strptime(dob_raw, "%d%m%Y").strftime("%Y-%m-%d")
    except ValueError:
        dob = None

    try:
        expiry = datetime.strptime(expiry_raw, "%d%m%Y").strftime("%Y-%m-%d")
    except ValueError:
        expiry = None

    return {
        "document_number": document_number,
        "nationality": nationality,
        "date_of_birth": dob,
        "sex": sex,
        "date_of_expiry": expiry,
        "raw": line
    }


# ---------------------------------------------------------
# Parse standard ICAO TD3 passport MRZ
# ---------------------------------------------------------

def parse_standard_mrz(line1: str, line2: str):
    """
    Parse ICAO TD3 passport MRZ.

    A valid passport MRZ consists of:
        Line 1 -> P< + issuing state + name
        Line 2 -> document number + check digit +
                  nationality + DOB + check digit +
                  sex + expiry + check digit + ...

    We only accept line2 when it has the expected
    structural pattern.
    """

    line1 = clean_ocr_mrz(line1)
    line2 = clean_ocr_mrz(line2)

    # -----------------------------------------------------
    # Line 1 must be a passport MRZ name line
    # -----------------------------------------------------

    if not line1.startswith("P<"):
        return None

    line1_padded = line1[:44].ljust(44, "<")
    issuing_state = line1_padded[2:5]
    name_field = line1_padded[5:44]

    # Demo/specimen passports sometimes put the literal marker SPECIMEN where
    # a real TD3 line would contain issuing state + surname. Treat the text
    # after that marker as the displayed mock identity, without affecting real
    # ICAO lines.
    specimen_match = re.match(r"^P<<*SPECIMEN<<", line1)
    if specimen_match:
        issuing_state = None
        name_field = line1[specimen_match.end():44]
    name_parts = name_field.split("<<", 1)
    surname = " ".join(
        part for part in name_parts[0].split("<") if part
    ) or None
    given_names = None
    if len(name_parts) > 1:
        given_names = " ".join(
            part for part in name_parts[1].split("<") if part
        ) or None
    full_name = " ".join(
        value for value in (given_names, surname) if value
    ) or None

    # -----------------------------------------------------
    # TD3 passport MRZ lines are normally 44 characters.
    # Allow a little OCR variation, but reject obviously
    # invalid lines.
    # -----------------------------------------------------

    if len(line2) < 35:
        return None

    line2_padded, positional_corrections = normalize_td3_line2(line2)

    # -----------------------------------------------------
    # Validate the basic TD3 structure.
    #
    # Positions:
    #
    # 0-8    document number
    # 9      check digit
    # 10-12  nationality
    # 13-18  DOB YYMMDD
    # 19     DOB check digit
    # 20     sex
    # 21-26  expiry YYMMDD
    # 27     expiry check digit
    # -----------------------------------------------------

    nationality = line2_padded[10:13]

    dob_raw = line2_padded[13:19]

    sex_char = line2_padded[20]

    expiry_raw = line2_padded[21:27]

    # -----------------------------------------------------
    # Nationality must be exactly 3 letters
    # -----------------------------------------------------

    if not re.fullmatch(r"[A-Z]{3}", nationality):
        return None

    # -----------------------------------------------------
    # DOB must contain six digits
    # -----------------------------------------------------

    if not re.fullmatch(r"\d{6}", dob_raw):
        return None

    # -----------------------------------------------------
    # Sex must be M, F or <
    # -----------------------------------------------------

    if sex_char not in {"M", "F", "<"}:
        return None

    # -----------------------------------------------------
    # Expiry must contain six digits
    # -----------------------------------------------------

    if not re.fullmatch(r"\d{6}", expiry_raw):
        return None

    # -----------------------------------------------------
    # Document number
    # -----------------------------------------------------

    document_field, ocr_corrections = correct_document_field(
        line2_padded[:44]
    )

    raw_doc_num = document_field.replace(
        "<",
        ""
    ).strip()

    if not raw_doc_num:
        return None

    # -----------------------------------------------------
    # Parse dates
    # -----------------------------------------------------

    dob = parse_mrz_date(
        dob_raw,
        is_expiry=False
    )

    expiry = parse_mrz_date(
        expiry_raw,
        is_expiry=True
    )

    # -----------------------------------------------------
    # Sex
    # -----------------------------------------------------

    sex = (
        sex_char
        if sex_char in {"M", "F"}
        else None
    )

    # -----------------------------------------------------
    # Final record
    # -----------------------------------------------------

    checksum_result = validate_td3_line2(
        line2_padded[:44],
        document_field=document_field,
    )

    return {
        "name": full_name,
        "surname": surname,
        "given_names": given_names,
        "issuing_state": issuing_state,
        "document_number": raw_doc_num,
        "nationality": nationality,
        "date_of_birth": dob,
        "sex": sex,
        "date_of_expiry": expiry,
        "raw": [
            line1,
            line2
        ],
        "checksums": checksum_result,
        "ocr_corrections": positional_corrections + ocr_corrections,
    }


# ---------------------------------------------------------
# Main MRZ analysis function
# ---------------------------------------------------------

def analyze_mrz(ocr_items):
    """
    Analyze OCR output for ONE uploaded identity document.

    Returns at most one MRZ record.
    Standard ICAO TD3 MRZ is preferred over the
    synthetic fallback format.
    """

    lines = extract_mrz_lines(ocr_items)

    # -----------------------------------------
    # 1. Prefer a proper two-line TD3 passport
    # -----------------------------------------

    for i in range(len(lines) - 1):
        line1 = lines[i]
        line2 = lines[i + 1]

        if line1.startswith("P<"):
            standard = parse_standard_mrz(
                line1,
                line2,
            )

            if standard:
                return {
                    "mrz_detected": True,
                    "lines_detected": lines,
                    "records": [standard],
                }

    # -----------------------------------------
    # 2. Fallback: synthetic dataset format
    # -----------------------------------------

    synthetic_candidates = []

    for line in lines:
        synthetic = parse_synthetic_mrz(line)

        if synthetic:
            synthetic_candidates.append(
                synthetic
            )

    # Nothing found
    if not synthetic_candidates:
        return {
            "mrz_detected": False,
            "lines_detected": lines,
            "records": [],
        }

    # We process one uploaded document at a time,
    # so return one candidate only.
    #
    # For now take the last valid synthetic MRZ,
    # because MRZ content is normally toward the
    # bottom of the document/OCR ordering.
    selected = synthetic_candidates[-1]

    return {
        "mrz_detected": True,
        "lines_detected": lines,
        "records": [selected],
    }


# ---------------------------------------------------------
# Standalone Execution / Test Block
# ---------------------------------------------------------

if __name__ == "__main__":
    # Dynamically locate project root (identity-verification folder)
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    OCR_FILE = PROJECT_ROOT / "datasets" / "processed" / "ocr_text.json"

    if OCR_FILE.exists():
        with open(OCR_FILE, "r", encoding="utf-8") as file:
            ocr_items = json.load(file)

        result = analyze_mrz(ocr_items)

        print("=" * 60)
        print("MRZ ANALYSIS (STANDALONE TEST)")
        print("=" * 60)
        print()
        print(json.dumps(result, indent=4))
    else:
        print(f"Error: OCR file not found at {OCR_FILE}")
