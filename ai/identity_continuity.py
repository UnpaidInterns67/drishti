"""Explain identity continuity across border screening events."""

from __future__ import annotations


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _graph(
    identity,
    document_type,
    matches,
    prior_crossings,
    has_conflict,
    current_crossing=None,
):
    """Build a small deterministic graph for the officer console."""
    nodes = [{
        "id": "biometric:current",
        "type": "biometric",
        "label": "Live biometric",
        "subtitle": "SFace identity cluster",
        "state": "conflict" if has_conflict else "trusted",
        "current": True,
    }]
    edges = []
    seen_nodes = {"biometric:current"}

    current_name = identity.get("name") or identity.get("full_name") or "Current identity"
    current_dob = identity.get("date_of_birth")
    current_document = (
        identity.get("document_number")
        or identity.get("passport_number")
        or identity.get("visa_number")
    )
    profiles = [{
        "key": "current",
        "name": current_name,
        "dob": current_dob,
        "document": current_document,
        "document_type": document_type,
        "checkpoint": (current_crossing or {}).get("checkpoint_code"),
        "movement": (current_crossing or {}).get("movement"),
        "current": True,
        "state": "conflict" if has_conflict else "current",
    }]
    for index, event in enumerate(prior_crossings):
        profiles.append({
            "key": f"prior-{index}",
            "name": event.get("full_name") or "Previous identity",
            "dob": event.get("date_of_birth"),
            "document": event.get("document_number"),
            "document_type": event.get("document_type"),
            "checkpoint": event.get("checkpoint_code"),
            "movement": event.get("movement"),
            "created_at": event.get("created_at"),
            "current": False,
            "state": "trusted",
        })

    for profile in profiles:
        profile_id = f"profile:{profile['key']}"
        nodes.append({
            "id": profile_id,
            "type": "profile",
            "label": profile["name"],
            "subtitle": profile.get("dob") or "DOB unavailable",
            "state": profile["state"],
            "current": profile["current"],
        })
        edges.append({
            "source": "biometric:current",
            "target": profile_id,
            "label": "BIOMETRIC MATCH",
            "state": "conflict" if profile["current"] and has_conflict else "match",
        })

        document = profile.get("document")
        if document:
            document_id = f"document:{document}"
            if document_id not in seen_nodes:
                nodes.append({
                    "id": document_id,
                    "type": "document",
                    "label": document,
                    "subtitle": (profile.get("document_type") or "document").upper(),
                    "state": profile["state"],
                    "current": profile["current"],
                })
                seen_nodes.add(document_id)
            edges.append({
                "source": profile_id,
                "target": document_id,
                "label": "PRESENTED",
                "state": "conflict" if profile["current"] and has_conflict else "link",
            })

            checkpoint = profile.get("checkpoint")
            if checkpoint:
                checkpoint_id = f"checkpoint:{checkpoint}"
                if checkpoint_id not in seen_nodes:
                    nodes.append({
                        "id": checkpoint_id,
                        "type": "checkpoint",
                        "label": checkpoint,
                        "subtitle": profile.get("movement") or "BORDER CROSSING",
                        "state": "neutral",
                        "current": False,
                    })
                    seen_nodes.add(checkpoint_id)
                edges.append({
                    "source": document_id,
                    "target": checkpoint_id,
                    "label": "OBSERVED AT",
                    "state": "link",
                })

    # A biometric match may exist before a crossing timeline was recorded.
    for match in matches:
        document = match.get("document_number")
        document_id = f"document:{document}"
        if document and document_id not in seen_nodes:
            nodes.append({
                "id": document_id,
                "type": "document",
                "label": document,
                "subtitle": "MATCHED DOCUMENT",
                "state": "conflict" if match.get("identity_conflict") else "trusted",
                "current": False,
            })
            edges.append({
                "source": "biometric:current",
                "target": document_id,
                "label": f"FACE {float(match.get('similarity', 0) or 0) * 100:.1f}%",
                "state": "conflict" if match.get("identity_conflict") else "match",
            })
            seen_nodes.add(document_id)

    return {"nodes": nodes, "edges": edges}


def build_continuity_assessment(
    identity: dict,
    document_type: str | None,
    duplicate_result: dict | None,
    prior_crossings: list[dict] | None,
    current_crossing: dict | None = None,
) -> dict:
    """Turn biometric links and biographic differences into officer evidence."""
    duplicate_result = duplicate_result or {}
    prior_crossings = prior_crossings or []
    matches = duplicate_result.get("matches") or []
    conflicts = duplicate_result.get("duplicate_matches") or []
    same_identity = duplicate_result.get("same_identity_matches") or []

    conflict_fields = _unique(
        field
        for match in conflicts
        for field in match.get("biographic_comparison", {}).get("conflicts", [])
    )
    linked_documents = _unique(
        [
            identity.get("document_number")
            or identity.get("passport_number")
            or identity.get("visa_number")
        ]
        + [match.get("document_number") for match in matches]
        + [event.get("document_number") for event in prior_crossings]
    )
    linked_identity_ids = _unique(match.get("identity_id") for match in matches)

    alerts = []
    if conflicts:
        alerts.append({
            "code": "SAME_FACE_DIFFERENT_IDENTITY",
            "severity": "CRITICAL",
            "message": (
                "The live face matches a previous traveller, but trusted "
                "identity details conflict."
            ),
            "conflicting_fields": conflict_fields,
            "strongest_face_similarity": max(
                float(match.get("similarity", 0) or 0) for match in conflicts
            ),
        })
    elif same_identity and len(linked_documents) > 1:
        alerts.append({
            "code": "KNOWN_TRAVELLER_NEW_DOCUMENT",
            "severity": "INFO",
            "message": (
                "The face and biographics match a known traveller using a "
                "different document."
            ),
        })

    if conflicts:
        status = "IDENTITY_CONFLICT"
        summary = (
            "Possible identity substitution: the same biometric identity is "
            "linked to conflicting personal details."
        )
    elif prior_crossings or same_identity:
        status = "CONTINUITY_CONFIRMED"
        summary = (
            f"Traveller continuity confirmed across {len(prior_crossings)} "
            "prior crossing(s)."
        )
    else:
        status = "NEW_TRAVELLER"
        summary = "No previous biometric identity or crossing was linked."

    return {
        "status": status,
        "summary": summary,
        "document_type": document_type,
        "linked_identity_ids": linked_identity_ids,
        "linked_document_count": len(linked_documents),
        "prior_crossing_count": len(prior_crossings),
        "conflicting_fields": conflict_fields,
        "alerts": alerts,
        "timeline": prior_crossings,
        "graph": _graph(
            identity,
            document_type,
            matches,
            prior_crossings,
            bool(conflicts),
            current_crossing,
        ),
    }
