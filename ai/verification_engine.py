"""Combine document, biometric, forensic, and watchlist screening results."""


REASON_MESSAGES = {
    "NO_DOCUMENT_RESULT": "No usable document record was produced.",
    "MULTIPLE_DOCUMENT_RECORDS": "More than one document identity was detected in a single screening.",
    "MRZ_NOT_DETECTED": "The required machine-readable zone could not be read.",
    "MRZ_CHECKSUM_FAILED": "One or more MRZ check digits are inconsistent with the encoded data.",
    "DOCUMENT_EXPIRED": "The presented credential is past its stated expiry date.",
    "DOCUMENT_VALIDATION_FAILED": "The document did not meet the configured field and date validation threshold.",
    "UIDAI_SIGNATURE_INVALID": "The Aadhaar Secure QR signature could not be verified with a trusted UIDAI certificate.",
    "AADHAAR_FRONT_QR_MISMATCH": "Visible Aadhaar fields conflict with issuer-signed Secure QR data.",
    "AADHAAR_PHOTO_QR_MISMATCH": "The visible Aadhaar photograph differs from the portrait inside the signed Secure QR.",
    "AADHAAR_PHOTO_QR_INCONCLUSIVE": "The visible Aadhaar photograph could not be compared reliably with the signed QR portrait.",
    "OCR_CORRECTION_REQUIRES_REVIEW": "An OCR correction lacks an independent trusted confirmation.",
    "OCR_MRZ_MISMATCH": "Visible document fields conflict with machine-readable-zone values.",
    "POSSIBLE_TAMPERING": "Multiple image-forensic signals require document examination.",
    "IMAGE_CAPTURE_QUALITY_WARNING": "Capture quality is weak, but independent machine evidence was recovered.",
    "IMAGE_RECAPTURE_REQUIRED": "Capture quality is insufficient for reliable screening; recapture the document.",
    "FACE_MATCH_BORDERLINE": "Face similarity lies within the configured uncertainty band.",
    "FACE_SAMPLE_UNSTABLE": "Similarity changed too much across quality-passed live frames.",
    "LIVENESS_FAILED": "The live-person challenge was not completed successfully.",
    "FACE_MISMATCH": "The live face did not match the document portrait at the configured threshold.",
    "WATCHLIST_MATCH": "An authorized watchlist or blacklisted-document signal was returned.",
    "POSSIBLE_MULTIPLE_IDENTITIES": "A matching biometric is linked to conflicting identity attributes.",
}


def combine_verification(
    document_result: dict,
    face_result: dict,
    watchlist_result: dict | None = None,
) -> dict:
    """Return an explainable triage decision for one screening session."""
    document_result = document_result or {}
    face_result = face_result or {}
    watchlist_result = watchlist_result or {}

    reasons = []
    evidence = []
    risk_score = 0.0

    def add_reason(code, severity="MEDIUM", score=0, details=None):
        nonlocal risk_score
        if code in reasons:
            return
        reasons.append(code)
        # Passing checks must not dilute the strongest adverse signal.
        risk_score = max(risk_score, float(score))
        item = {"code": code, "severity": severity}
        item["message"] = REASON_MESSAGES.get(
            code,
            code.replace("_", " ").capitalize(),
        )
        if details is not None:
            item["details"] = details
        evidence.append(item)

    documents = document_result.get("documents", [])
    document_ok = False

    if not documents:
        add_reason("NO_DOCUMENT_RESULT", "HIGH", 80)
    elif len(documents) > 1:
        add_reason(
            "MULTIPLE_DOCUMENT_RECORDS",
            "HIGH",
            70,
            {"count": len(documents)},
        )
    else:
        document = documents[0]
        document_ok = True

        mrz = document.get("mrz", {})
        expiry = document.get("expiry", {})
        validation = document.get("validation", {})
        cross_validation = document.get("cross_validation", {})
        document_risk = document.get("risk", {})
        forensics = document.get("forensics", {})
        extraction = document.get("extraction", {})
        issuer_verification = document.get("issuer_verification")

        risk_score = max(
            risk_score,
            float(document_risk.get("risk_score", 0) or 0),
        )

        mrz_required = mrz.get(
            "required",
            document.get("document_type") == "passport",
        )
        if mrz_required and not mrz.get("detected", False):
            document_ok = False
            add_reason("MRZ_NOT_DETECTED", "MEDIUM", 30)

        checksums = mrz.get("checksums")
        if checksums is not None and not checksums.get("valid", False):
            document_ok = False
            failed_checks = [
                name
                for name, result in checksums.get("checks", {}).items()
                if not result.get("valid", False)
            ]
            add_reason(
                "MRZ_CHECKSUM_FAILED",
                "HIGH",
                50,
                {"failed_checks": failed_checks},
            )

        if expiry.get("status") == "EXPIRED":
            document_ok = False
            add_reason("DOCUMENT_EXPIRED", "CRITICAL", 80)

        for issue in validation.get("issues", []):
            add_reason(issue, "MEDIUM", 25)

        if float(validation.get("validation_score", 0) or 0) < 80:
            document_ok = False
            add_reason("DOCUMENT_VALIDATION_FAILED", "HIGH", 40)

        if (
            issuer_verification is not None
            and issuer_verification.get("signature_valid") is not True
        ):
            document_ok = False
            add_reason("UIDAI_SIGNATURE_INVALID", "CRITICAL", 100)

        if "AADHAAR_FRONT_QR_MISMATCH" in validation.get("issues", []):
            document_ok = False
            add_reason(
                "AADHAAR_FRONT_QR_MISMATCH",
                "CRITICAL",
                100,
                cross_validation,
            )

        if "AADHAAR_PHOTO_QR_MISMATCH" in validation.get("issues", []):
            document_ok = False
            add_reason(
                "AADHAAR_PHOTO_QR_MISMATCH",
                "CRITICAL",
                100,
                cross_validation.get("portrait"),
            )

        if "AADHAAR_PHOTO_QR_INCONCLUSIVE" in validation.get("issues", []):
            document_ok = False
            add_reason(
                "AADHAAR_PHOTO_QR_INCONCLUSIVE",
                "MEDIUM",
                35,
                cross_validation.get("portrait"),
            )

        unverified_corrections = [
            correction
            for correction in extraction.get("ocr_corrections", [])
            if not correction.get("independently_verified", False)
        ]
        if unverified_corrections:
            document_ok = False
            add_reason(
                "OCR_CORRECTION_REQUIRES_REVIEW",
                "MEDIUM",
                35,
                {"corrections": unverified_corrections},
            )

        mismatch_count = int(cross_validation.get("mismatches", 0) or 0)
        if mismatch_count:
            document_ok = False
            add_reason(
                "OCR_MRZ_MISMATCH",
                "HIGH",
                50,
                {"mismatches": mismatch_count},
            )

        forensic_overall = forensics.get("overall", {})
        capture_quality = forensic_overall.get("capture_quality", {})
        tampering_score = float(
            forensic_overall.get(
                "tampering_score",
                forensic_overall.get("score", 0),
            )
            or 0
        )
        if tampering_score >= 35:
            document_ok = False
            add_reason(
                "POSSIBLE_TAMPERING",
                "HIGH" if tampering_score >= 60 else "MEDIUM",
                tampering_score,
                {
                    "tampering_score": tampering_score,
                    "signals": forensic_overall.get("signals", []),
                },
            )

        if capture_quality.get("blocking"):
            strong_machine_evidence = bool(
                (mrz.get("checksums") or {}).get("valid")
                or (issuer_verification or {}).get("signature_valid") is True
            )
            if strong_machine_evidence:
                add_reason(
                    "IMAGE_CAPTURE_QUALITY_WARNING",
                    "LOW",
                    15,
                    capture_quality,
                )
            else:
                document_ok = False
                add_reason(
                    "IMAGE_RECAPTURE_REQUIRED",
                    "MEDIUM",
                    35,
                    capture_quality,
                )

        risk_decision = document_risk.get("decision", "REVIEW")
        if risk_decision != "PASS":
            document_ok = False
            add_reason(
                f"DOCUMENT_RISK_{risk_decision}",
                "HIGH" if risk_decision == "FLAG" else "MEDIUM",
                document_risk.get("risk_score", 35),
            )

    liveness_ok = bool(face_result.get("liveness_passed", False))
    face_ok = bool(face_result.get("face_match", False))

    similarity = face_result.get("face_similarity")
    threshold = float(face_result.get("face_match_threshold", 0.40) or 0.40)
    margin = float(face_result.get("face_match_margin", 0.04) or 0.04)
    if (
        liveness_ok
        and similarity is not None
        and abs(float(similarity) - threshold) <= margin
    ):
        add_reason(
            "FACE_MATCH_BORDERLINE",
            "MEDIUM",
            40,
            {
                "similarity": float(similarity),
                "threshold": threshold,
                "uncertainty_margin": margin,
            },
        )

    similarity_spread = float(face_result.get("face_similarity_spread", 0) or 0)
    if liveness_ok and similarity_spread > 0.12:
        add_reason(
            "FACE_SAMPLE_UNSTABLE",
            "MEDIUM",
            40,
            {
                "spread": similarity_spread,
                "samples": face_result.get("face_samples"),
            },
        )

    if not liveness_ok:
        add_reason("LIVENESS_FAILED", "HIGH", 50)
    if not face_ok:
        add_reason("FACE_MISMATCH", "CRITICAL", 75)

    watchlist_hit = bool(
        watchlist_result.get("match")
        or watchlist_result.get("blacklisted")
        or watchlist_result.get("document_blacklisted")
    )
    duplicate_identity = bool(watchlist_result.get("duplicate_identity"))
    watchlist_ok = not watchlist_hit and not duplicate_identity

    if watchlist_hit:
        add_reason("WATCHLIST_MATCH", "CRITICAL", 100)
    if duplicate_identity:
        add_reason("POSSIBLE_MULTIPLE_IDENTITIES", "CRITICAL", 90)

    critical_reject = any(
        reason in reasons
        for reason in (
            "DOCUMENT_EXPIRED",
            "FACE_MISMATCH",
            "WATCHLIST_MATCH",
            "POSSIBLE_MULTIPLE_IDENTITIES",
            "UIDAI_SIGNATURE_INVALID",
            "AADHAAR_FRONT_QR_MISMATCH",
            "AADHAAR_PHOTO_QR_MISMATCH",
        )
    )

    biometric_uncertain = bool(
        {"FACE_MATCH_BORDERLINE", "FACE_SAMPLE_UNSTABLE"} & set(reasons)
    )
    all_checks_passed = (
        document_ok and liveness_ok and face_ok and watchlist_ok
        and not biometric_uncertain
    )
    if critical_reject or risk_score >= 70:
        decision = "REJECT"
    elif not all_checks_passed or risk_score >= 35:
        # Uncertain evidence asks for another capture or check.
        # The officer still records the final disposition separately.
        decision = "RETRY"
    else:
        decision = "APPROVE"

    verified = decision == "APPROVE"
    risk_score = round(min(100.0, risk_score), 2)

    if risk_score >= 70:
        risk_level = "HIGH"
    elif risk_score >= 35:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "verified": verified,
        "decision": decision,
        "manual_review": False,
        "officer_disposition_required": True,
        "retry_required": decision == "RETRY",
        "risk_score": risk_score,
        "risk_level": risk_level,
        "checks": {
            "document": document_ok,
            "liveness": liveness_ok,
            "face_match": face_ok,
            "watchlist": watchlist_ok,
        },
        "document": document_result,
        "biometrics": face_result,
        "watchlist": watchlist_result,
        "reasons": reasons,
        "evidence": evidence,
        "decision_context": {
            "scope": "AUTOMATED_TRIAGE",
            "final_authority": "AUTHORIZED_BORDER_OFFICER",
            "recommendation_only": True,
        },
    }
