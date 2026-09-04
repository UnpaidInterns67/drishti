"""One-to-many face-embedding search for duplicate identity screening."""

from __future__ import annotations

from difflib import SequenceMatcher

import numpy as np


def _normalize_document_number(value) -> str:
    return "".join(
        character
        for character in str(value or "").upper()
        if character.isalnum()
    )


def _normalize_name(value) -> str:
    return "".join(
        character
        for character in str(value or "").upper()
        if character.isalnum()
    )


def _document_relationship(current: str, stored: str) -> str:
    if not current or not stored:
        return "UNKNOWN"
    if current == stored:
        return "SAME_DOCUMENT"
    # Aadhaar Secure QR exposes only the last four digits. A masked identifier
    # that agrees with a stored full identifier is compatible, not different.
    if (len(current) == 4 and stored.endswith(current)) or (
        len(stored) == 4 and current.endswith(stored)
    ):
        return "MASKED_IDENTIFIER_MATCH"
    return "DIFFERENT_DOCUMENT"


def _compare_biographics(
    current_name,
    current_date_of_birth,
    stored_name,
    stored_date_of_birth,
) -> dict:
    current_name = _normalize_name(current_name)
    stored_name = _normalize_name(stored_name)
    current_dob = str(current_date_of_birth or "").strip()
    stored_dob = str(stored_date_of_birth or "").strip()

    name_similarity = None
    name_match = None
    if current_name and stored_name:
        name_similarity = SequenceMatcher(None, current_name, stored_name).ratio()
        name_match = name_similarity >= 0.82

    dob_match = None
    if current_dob and stored_dob:
        dob_match = current_dob == stored_dob

    compared = [value for value in (name_match, dob_match) if value is not None]
    return {
        "name_match": name_match,
        "name_similarity": round(name_similarity, 4) if name_similarity is not None else None,
        "date_of_birth_match": dob_match,
        "consistent": bool(compared) and all(compared),
        "conflicts": [
            field
            for field, matches in (("name", name_match), ("date_of_birth", dob_match))
            if matches is False
        ],
    }


def cosine_similarity(embedding_a, embedding_b) -> float:
    a = np.asarray(embedding_a, dtype=np.float32).reshape(-1)
    b = np.asarray(embedding_b, dtype=np.float32).reshape(-1)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("Face embeddings must have the same non-zero shape")
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denominator)


def find_duplicate_identities(
    query_embedding,
    enrolled_records,
    document_number=None,
    full_name=None,
    date_of_birth=None,
    threshold=0.50,
    limit=5,
) -> dict:
    """Find a face enrolled with conflicting identity attributes.

    ``enrolled_records`` is deliberately storage-agnostic so a backend can
    supply rows from any database. Each row should contain ``embedding`` and
    may contain identity/document and biographic attributes. A person holding
    multiple documents is one identity, not a duplicate; a duplicate is raised
    only when a biometric match has a genuinely different identifier and
    conflicting trusted biographics.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")

    matches = []
    for record in enrolled_records:
        embedding = record.get("embedding")
        if embedding is None:
            continue
        try:
            similarity = cosine_similarity(query_embedding, embedding)
        except (TypeError, ValueError):
            continue
        if similarity < threshold:
            continue
        enrolled_document = record.get("document_number")
        current_document = _normalize_document_number(document_number)
        stored_document = _normalize_document_number(enrolled_document)
        document_relationship = _document_relationship(current_document, stored_document)
        biographics = _compare_biographics(
            full_name,
            date_of_birth,
            record.get("full_name"),
            record.get("date_of_birth"),
        )
        same_identity = document_relationship in {
            "SAME_DOCUMENT",
            "MASKED_IDENTIFIER_MATCH",
        } or biographics["consistent"]
        identity_conflict = bool(
            document_relationship == "DIFFERENT_DOCUMENT"
            and biographics["conflicts"]
            and not same_identity
        )
        matches.append({
            "identity_id": record.get("identity_id"),
            "document_number": enrolled_document,
            "similarity": round(similarity, 4),
            "document_relationship": document_relationship,
            "different_document": document_relationship == "DIFFERENT_DOCUMENT",
            "same_identity": same_identity,
            "identity_conflict": identity_conflict,
            "biographic_comparison": biographics,
        })

    matches.sort(key=lambda match: match["similarity"], reverse=True)
    matches = matches[: max(0, int(limit))]
    duplicate_matches = [
        match for match in matches if match["identity_conflict"]
    ]
    same_identity_matches = [
        match for match in matches if match["same_identity"]
    ]

    return {
        "duplicate_identity": bool(duplicate_matches),
        "threshold": threshold,
        "matches": matches,
        "duplicate_matches": duplicate_matches,
        "same_identity_matches": same_identity_matches,
    }
