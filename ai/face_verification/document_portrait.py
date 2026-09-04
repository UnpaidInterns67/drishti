"""Compare a visible document photograph with an issuer-signed portrait."""

from __future__ import annotations

from pathlib import Path

import cv2

from .config import FACE_MATCH_UNCERTAINTY_MARGIN, RECOMMENDED_MATCH_THRESHOLD
from .face_engine import FaceEngine


def _face_evidence(engine: FaceEngine, face) -> dict:
    return {
        "box": list(engine.box(face)),
        "detection_confidence": round(engine.confidence(face), 4),
    }


def compare_document_portraits(
    visible_document_path: str | Path,
    signed_portrait_path: str | Path,
    *,
    threshold: float = RECOMMENDED_MATCH_THRESHOLD,
    uncertainty_margin: float = FACE_MATCH_UNCERTAINTY_MARGIN,
    engine: FaceEngine | None = None,
) -> dict:
    """Return MATCH, MISMATCH, or INCONCLUSIVE without exposing embeddings."""
    visible = cv2.imread(str(visible_document_path))
    signed = cv2.imread(str(signed_portrait_path))
    if visible is None or signed is None:
        return {
            "status": "INCONCLUSIVE",
            "match": None,
            "reason": "PORTRAIT_IMAGE_UNREADABLE",
        }

    face_engine = engine or FaceEngine()
    visible_faces = face_engine.detect_faces(visible)
    signed_faces = face_engine.detect_faces(signed)
    evidence = {
        "visible_face_count": len(visible_faces),
        "signed_face_count": len(signed_faces),
        "threshold": threshold,
        "uncertainty_margin": uncertainty_margin,
        "source": "VISIBLE_PHOTO_VS_UIDAI_SIGNED_QR_PORTRAIT",
    }

    if len(visible_faces) == 0:
        return {
            **evidence,
            "status": "INCONCLUSIVE",
            "match": None,
            "reason": "VISIBLE_DOCUMENT_PHOTO_NOT_DETECTED",
        }
    if len(signed_faces) == 0:
        return {
            **evidence,
            "status": "INCONCLUSIVE",
            "match": None,
            "reason": "SIGNED_QR_PORTRAIT_FACE_NOT_DETECTED",
        }

    # Document artwork can create YuNet false-positive candidates. The printed
    # portrait is normally the dominant face region, so use the largest
    # candidate and retain the candidate counts as inspectable evidence.
    visible_face = face_engine.largest_face(visible_faces)
    signed_face = face_engine.largest_face(signed_faces)
    try:
        visible_embedding = face_engine.embedding(visible, visible_face)
        signed_embedding = face_engine.embedding(signed, signed_face)
        similarity = face_engine.cosine_similarity(
            visible_embedding,
            signed_embedding,
        )
    except (cv2.error, ValueError):
        return {
            **evidence,
            "status": "INCONCLUSIVE",
            "match": None,
            "reason": "DOCUMENT_PORTRAIT_EMBEDDING_FAILED",
        }

    evidence.update({
        "similarity": round(float(similarity), 4),
        "visible_face": _face_evidence(face_engine, visible_face),
        "signed_face": _face_evidence(face_engine, signed_face),
        "candidate_selection": "LARGEST_DETECTED_FACE",
    })
    if similarity >= threshold:
        return {**evidence, "status": "MATCH", "match": True, "reason": None}
    if similarity < threshold - uncertainty_margin:
        return {
            **evidence,
            "status": "MISMATCH",
            "match": False,
            "reason": "VISIBLE_PHOTO_DIFFERS_FROM_SIGNED_QR_PORTRAIT",
        }
    return {
        **evidence,
        "status": "INCONCLUSIVE",
        "match": None,
        "reason": "DOCUMENT_PORTRAIT_SCORE_BORDERLINE",
    }
