"""Turn screening evidence into an explainable officer action plan."""

from __future__ import annotations


def _action(code, title, instruction, reason, actor="OFFICER"):
    return {
        "code": code,
        "title": title,
        "instruction": instruction,
        "reason": reason,
        "actor": actor,
    }


def build_secondary_inspection(
    final_result: dict,
    continuity: dict | None = None,
) -> dict:
    """Build a deterministic, inspectable next-action recommendation.

    This is decision support. It deliberately recommends escalation instead
    of claiming to make a coercive or legal decision on an officer's behalf.
    """
    final_result = final_result or {}
    continuity = continuity or {}
    reasons = set(final_result.get("reasons") or [])
    biometrics = final_result.get("biometrics") or {}
    watchlist = final_result.get("watchlist") or {}
    quality = biometrics.get("quality") or {}
    similarity = biometrics.get("face_similarity")
    threshold = float(biometrics.get("face_match_threshold", 0.40) or 0.40)
    margin = float(biometrics.get("face_match_margin", 0.04) or 0.04)
    continuity_status = continuity.get("status")

    path = []
    actions = []

    def signal(name, status, detail):
        path.append({"signal": name, "status": status, "detail": detail})

    watchlist_hit = bool(
        watchlist.get("match")
        or watchlist.get("blacklisted")
        or watchlist.get("document_blacklisted")
        or "WATCHLIST_MATCH" in reasons
    )
    signal(
        "Authorized watchlist",
        "ALERT" if watchlist_hit else "CLEAR",
        "Potential authorized-list match requires controlled escalation."
        if watchlist_hit else "No watchlist signal was returned.",
    )

    conflict = (
        continuity_status == "IDENTITY_CONFLICT"
        or "POSSIBLE_MULTIPLE_IDENTITIES" in reasons
    )
    signal(
        "Identity continuity",
        "ALERT" if conflict else "CLEAR",
        continuity.get("summary") or "No prior identity conflict was found.",
    )

    credential_invalid = bool(
        {
            "UIDAI_SIGNATURE_INVALID",
            "AADHAAR_FRONT_QR_MISMATCH",
            "AADHAAR_PHOTO_QR_MISMATCH",
        }
        & reasons
    )
    credential_review = bool(
        {
            "MRZ_NOT_DETECTED",
            "MRZ_CHECKSUM_FAILED",
            "DOCUMENT_VALIDATION_FAILED",
            "OCR_CORRECTION_REQUIRES_REVIEW",
            "OCR_MRZ_MISMATCH",
            "POSSIBLE_TAMPERING",
            "AADHAAR_PHOTO_QR_INCONCLUSIVE",
        }
        & reasons
    )
    signal(
        "Credential integrity",
        "ALERT" if credential_invalid else "REVIEW" if credential_review else "CLEAR",
        "Issuer or document evidence needs an additional credential check."
        if credential_invalid or credential_review
        else "Document checks did not produce an adverse integrity signal.",
    )

    liveness_ok = bool(biometrics.get("liveness_passed"))
    face_ok = bool(biometrics.get("face_match"))
    quality_ok = quality.get("passed", True) is not False
    unstable_sample = "FACE_SAMPLE_UNSTABLE" in reasons
    borderline = (
        similarity is not None
        and abs(float(similarity) - threshold) <= margin
    )
    face_detail = "Live face and document portrait are consistent."
    face_status = "CLEAR"
    if not quality_ok or biometrics.get("reason") == "live_embedding_failed":
        face_status = "RECAPTURE"
        face_detail = "Capture quality is insufficient for a dependable comparison."
    elif not liveness_ok:
        face_status = "RECAPTURE"
        face_detail = "The randomized live-person challenge was not completed."
    elif borderline or unstable_sample:
        face_status = "REVIEW"
        face_detail = (
            "The face score is inside the uncertainty band; a second independent "
            "capture is safer than an automatic decision."
        ) if borderline else "Face similarity varied too much across the stable frames."
    elif not face_ok:
        face_status = "ALERT"
        face_detail = "The stable multi-frame face comparison is below threshold."
    signal("Live biometric", face_status, face_detail)

    # Order matters: urgent identity and issuer alerts take priority over recapture.
    if watchlist_hit:
        actions.append(_action(
            "CONTROLLED_WATCHLIST_ESCALATION",
            "Route to controlled secondary inspection",
            "Keep the screening open and notify the authorized supervisor or unit for match resolution.",
            "A watchlist signal must be resolved by authorized personnel; the software must not clear it automatically.",
            "SUPERVISOR",
        ))
        status, priority = "DENY_AND_ESCALATE", "CRITICAL"
    elif conflict:
        fields = ", ".join(continuity.get("conflicting_fields") or [])
        actions.append(_action(
            "RESOLVE_IDENTITY_CONTINUITY",
            "Resolve same-face identity conflict",
            "Compare the presented credential with the linked crossing history and verify issuer provenance."
            + (f" Focus on: {fields}." if fields else ""),
            "The biometric links to conflicting biographic identities, which may indicate substitution or an incorrect historical record.",
            "SUPERVISOR",
        ))
        status, priority = "SUPERVISOR_REVIEW", "CRITICAL"
    elif credential_invalid:
        actions.append(_action(
            "REVERIFY_ISSUER_EVIDENCE",
            "Reverify credential provenance",
            "Use an authorized document reader or trusted issuer channel; do not rely on visible text alone.",
            "Signed issuer evidence is invalid or conflicts with the visible credential.",
            "SUPERVISOR",
        ))
        status, priority = "SUPERVISOR_REVIEW", "HIGH"
    elif "DOCUMENT_EXPIRED" in reasons:
        actions.append(_action(
            "CHECK_TRAVEL_AUTHORITY",
            "Verify travel authority",
            "Confirm whether an approved exception or alternate valid travel document exists.",
            "The presented credential is expired and cannot be cleared automatically.",
            "SUPERVISOR",
        ))
        status, priority = "SUPERVISOR_REVIEW", "HIGH"
    elif not quality_ok or biometrics.get("reason") == "live_embedding_failed":
        failures = quality.get("failures") or []
        guidance = {
            "move_closer": "Move closer until the face fills the oval.",
            "move_back": "Move slightly away from the camera.",
            "center_face": "Center the full face inside the oval.",
            "image_blurry": "Hold still and clean the camera lens.",
            "too_dark": "Move into even front lighting.",
            "too_bright": "Move away from glare or strong backlight.",
        }
        instruction = " ".join(guidance.get(item, "") for item in failures).strip()
        actions.append(_action(
            "GUIDED_BIOMETRIC_RECAPTURE",
            "Repeat guided face capture",
            instruction or "Center the face, use even lighting, hold still, and repeat the randomized challenge.",
            "The available frames are not strong enough to support a reliable identity comparison.",
        ))
        status, priority = "ACTION_REQUIRED", "MEDIUM"
    elif not liveness_ok:
        actions.append(_action(
            "REPEAT_RANDOM_LIVENESS",
            "Repeat randomized liveness once",
            "Restart capture and complete the new blink-and-turn sequence. Escalate if the second attempt fails.",
            "The live-person challenge was incomplete or timed out.",
        ))
        status, priority = "ACTION_REQUIRED", "HIGH"
    elif borderline or unstable_sample:
        actions.append(_action(
            "SECOND_INDEPENDENT_BIOMETRIC",
            "Capture a second biometric sample",
            "Reposition the traveller, restart the randomized challenge, and compare a new multi-frame sample.",
            f"Similarity {float(similarity):.3f} is within ±{margin:.2f} of the {threshold:.2f} threshold."
            if borderline else "Similarity varied too much across the captured frames.",
        ))
        status, priority = "ACTION_REQUIRED", "HIGH"
    elif not face_ok:
        actions.append(_action(
            "SUPERVISOR_FACE_RESOLUTION",
            "Resolve biometric mismatch",
            "Verify document ownership using approved secondary procedures and record the supervisor outcome.",
            "Multiple stable frames remain below the configured face-match threshold.",
            "SUPERVISOR",
        ))
        status, priority = "SUPERVISOR_REVIEW", "HIGH"
    elif credential_review or final_result.get("decision") == "RETRY":
        actions.append(_action(
            "TARGETED_DOCUMENT_RECAPTURE",
            "Repeat the affected document check",
            "Recapture the credential flat, fully visible, glare-free, and verify the flagged field or forensic signal.",
            "Document evidence is uncertain; only the affected check needs to be repeated.",
        ))
        status, priority = "ACTION_REQUIRED", "MEDIUM"
    else:
        actions.append(_action(
            "CLEAR_STANDARD_LANE",
            "Continue standard officer processing",
            "Complete the normal statutory border procedure for this checkpoint.",
            "Credential, liveness, face, continuity, and watchlist signals contain no unresolved alert.",
        ))
        status, priority = "CLEAR", "ROUTINE"

    primary = actions[0]
    headline = primary["title"]
    return {
        "status": status,
        "priority": priority,
        "headline": headline,
        "summary": primary["reason"],
        "primary_action": primary,
        "actions": actions,
        "decision_path": path,
        "advisory": (
            "Decision-support recommendation only. The authorized officer remains "
            "responsible for the final action under applicable procedure."
        ),
    }
