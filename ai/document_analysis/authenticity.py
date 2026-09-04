"""Explain what authenticity evidence was and was not available."""

from __future__ import annotations


def assess_authenticity(document: dict) -> dict:
    """Return an honest assurance statement for the current evidence sources."""
    document_type = document.get("document_type", "unknown")
    issuer = document.get("issuer_verification") or {}
    mrz = document.get("mrz") or {}
    checksums = mrz.get("checksums") or {}

    checks = []
    if mrz.get("required") or mrz.get("detected"):
        checks.append({
            "check": "MRZ_CHECK_DIGITS",
            "status": "PASS" if checksums.get("valid") else "FAIL",
            "meaning": "Detects inconsistent machine-readable data; it is not issuer authentication.",
        })

    signature_valid = issuer.get("signature_valid") is True
    if issuer:
        checks.append({
            "check": "ISSUER_DIGITAL_SIGNATURE",
            "status": "PASS" if signature_valid else "FAIL",
            "provider": issuer.get("provider"),
            "method": issuer.get("method"),
        })

    if signature_valid:
        level = "CRYPTOGRAPHIC_ISSUER_EVIDENCE"
        status = "ISSUER_VERIFIED"
        summary = "Issuer-signed identity data was cryptographically verified."
    elif checksums.get("valid"):
        level = "MACHINE_CONSISTENCY_ONLY"
        status = "ISSUER_NOT_VERIFIED"
        summary = "MRZ structure is internally consistent, but no issuer signature was available."
    else:
        level = "VISIBLE_SCREENING_ONLY"
        status = "ISSUER_NOT_VERIFIED"
        summary = "The result is based on visible-zone extraction and forensic screening only."

    next_steps = []
    if document_type == "passport" and not signature_valid:
        checks.append({
            "check": "E_PASSPORT_CHIP",
            "status": "NOT_PERFORMED",
            "meaning": "Requires a compatible NFC document reader and trusted certificate gateway.",
        })
        next_steps.append("Read and authenticate the e-passport chip when reader hardware is available.")
    elif document_type in {"visa", "national_id", "driving_license", "permit"}:
        next_steps.append("Query the authorized issuing-authority or immigration system when connected.")

    return {
        "status": status,
        "assurance_level": level,
        "summary": summary,
        "checks": checks,
        "next_steps": next_steps,
        "limitations": [
            "Image forensics cannot by itself prove a credential is genuine.",
            "No live government or international database response was available unless explicitly shown.",
        ],
    }
