"""Synthetic walkthroughs: no images, personal data, or operational database access."""

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from ai.document_analysis.analyzer import build_document_record
from ai.document_analysis.icao import calculate_check_digit
from ai.face_verification.identity_search import find_duplicate_identities
from ai.identity_continuity import build_continuity_assessment
from ai.secondary_inspection import build_secondary_inspection
from ai.verification_engine import combine_verification

from .config import settings
from .schemas import OfficerDispositionRequest

NOTICE = (
    "SYNTHETIC DEMO — simulated OCR, capture and liveness; toy vectors, no real face. "
    "No issuer, chip or government database checks performed. "
    "Not an operational clearance."
)
SCENARIOS = {
    "clean-clearance": "Clean clearance",
    "document-inconsistency": "Document inconsistency",
    "poor-capture": "Poor capture / recapture",
    "identity-conflict": "Same-face conflicting identity",
}
RUN_LIFETIME_SECONDS = 30 * 60
MAX_DEMO_RUNS = 100

router = APIRouter(prefix=f"{settings.api_prefix}/demo", tags=["synthetic-demo"])
# Separate from the operational session store: rehearsals never reach the database.
_runs = OrderedDict()
_lock = RLock()


def enabled():
    if not settings.demo_enabled or settings.is_production:
        raise HTTPException(404, detail={"code": "DEMO_DISABLED"})


def _passport_mrz():
    """Build an internally consistent MRZ for the fictional passport."""
    document_number = "DEMO0001<"
    date_of_birth = "900101"
    date_of_expiry = "491231"
    optional_data = "<<<<<<<<<<<<<<"

    checked_number = document_number + calculate_check_digit(document_number)
    checked_birth = date_of_birth + calculate_check_digit(date_of_birth)
    checked_expiry = date_of_expiry + calculate_check_digit(date_of_expiry)
    checked_optional = optional_data + calculate_check_digit(optional_data)

    # Nationality and sex appear in the line, but not in its composite checksum.
    composite_data = checked_number + checked_birth + checked_expiry + checked_optional
    return (
        checked_number + "UTO" + checked_birth + "F"
        + checked_expiry + checked_optional + calculate_check_digit(composite_data)
    )


def _document_fixture(scenario, needs_recapture):
    visible_number = "DEMO0002" if scenario == "document-inconsistency" else "DEMO0001"
    lines = [
        "PASSPORT",
        "Name: SYNTHETIC DEMO PERSON",
        f"Passport No: {visible_number}",
        "Nationality: UTO",
        "Date of Birth: 01/01/1990",
        "Date of Expiry: 31/12/2049",
        "Sex: F",
        "P<UTOPERSON<<SYNTHETIC<DEMO".ljust(44, "<"),
        _passport_mrz(),
    ]
    if needs_recapture:
        # Simulate a capture where neither MRZ line could be read.
        lines = lines[:-2]

    ocr_items = []
    for index, text in enumerate(lines):
        top = index * 20
        ocr_items.append({
            "text": text,
            "confidence": 0.99,
            "bbox": [[0, top], [400, top], [400, top + 10], [0, top + 10]],
        })

    document = build_document_record(ocr_items)
    document["synthetic"] = True
    document["documents"][0]["forensics"] = {
        "synthetic": True,
        "overall": {
            "tampering_score": 0,
            "capture_quality": {
                "blocking": needs_recapture,
                "passed": not needs_recapture,
                "guidance": [
                    "Hold still, remove glare and include the entire document."
                ] if needs_recapture else [],
            },
        },
    }
    return document


def _identity_history_fixture(identity, has_conflict):
    """Compare toy vectors, then build the fictional crossing shown in the graph."""
    prior_identity = {
        "identity_id": "synthetic-prior",
        "document_number": "DEMO0099",
        "full_name": "FICTIONAL SAMPLE ALPHA",
        "date_of_birth": "1980-02-02",
        "embedding": [1.0, 0.0, 0.0],
    }
    duplicate = find_duplicate_identities(
        [1.0, 0.0, 0.0],
        [prior_identity] if has_conflict else [],
        document_number="DEMO0001",
        full_name=identity.get("name"),
        date_of_birth=identity.get("date_of_birth"),
    )
    crossings = []
    if has_conflict:
        crossing = {
            key: value for key, value in prior_identity.items() if key != "embedding"
        }
        crossing.update(
            synthetic=True,
            document_type="passport",
            checkpoint_code="DEMO-POST",
            movement="EXIT",
            created_at="2026-01-01T10:00:00+00:00",
            decision="APPROVE",
        )
        crossings.append(crossing)
    return duplicate, crossings


def fixture(scenario, recaptured=False):
    """Exercise real parsers and policy with explicitly fabricated observations."""
    needs_recapture = scenario == "poor-capture" and not recaptured
    document = _document_fixture(scenario, needs_recapture)
    face = {
        "synthetic": True,
        "face_match": True,
        "face_similarity": 0.85,
        "face_match_threshold": 0.4,
        "liveness_passed": True,
        "liveness_score": 1.0,
        "verification_passed": True,
    }
    identity = document["documents"][0]["identity"]
    duplicate, crossings = _identity_history_fixture(
        identity, has_conflict=scenario == "identity-conflict"
    )
    border_context = {
        "checkpoint_code": "DEMO-POST",
        "movement": "ENTRY",
        "lane": "SYNTHETIC",
    }
    continuity = build_continuity_assessment(
        identity, "passport", duplicate, crossings, border_context
    )
    final = combine_verification(document, face, {
        "synthetic": True,
        "duplicate_identity": duplicate["duplicate_identity"],
        "external_checks": "NOT_PERFORMED",
    })
    for evidence in final["evidence"]:
        if evidence["code"] == "OCR_MRZ_MISMATCH":
            evidence["message"] = (
                "Synthetic visible passport number DEMO0002 conflicts with "
                "MRZ number DEMO0001. Inspect both sources."
            )
    final.update(
        synthetic=True,
        continuity=continuity,
        border_context=border_context,
        secondary_inspection=build_secondary_inspection(final, continuity),
    )
    return {
        "synthetic": True,
        "demo": {"scenario": scenario, "notice": NOTICE, "recaptured": recaptured},
        "document": document,
        "face": face,
        "duplicate_identity": duplicate,
        "final": final,
        "status": final["decision"],
        "face_session_active": False,
    }


def event(run, name):
    disposition = run["snapshot"]["final"].get("officer_disposition", {})
    run["events"].append({
        "event_type": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {"synthetic": True, "decision": disposition.get("decision")},
    })


def get_run(run_id, request):
    enabled()
    run = _runs.get(run_id)
    # Use the same response for a missing, expired or another officer's run.
    if (
        not run
        or run["owner"] != request.state.officer["officer_id"]
        or monotonic() - run["started"] > RUN_LIFETIME_SECONDS
    ):
        raise HTTPException(404, detail={"code": "DEMO_RUN_NOT_FOUND"})
    return run


@router.get("/scenarios")
def scenarios():
    demo_available = settings.demo_enabled and not settings.is_production
    return {
        "enabled": demo_available,
        "notice": NOTICE,
        "scenarios": [
            {"id": scenario_id, "title": title}
            for scenario_id, title in SCENARIOS.items()
        ] if demo_available else [],
    }


@router.post("/scenarios/{scenario}")
def start(scenario: str, request: Request):
    enabled()
    if scenario not in SCENARIOS:
        raise HTTPException(404, detail={"code": "DEMO_SCENARIO_NOT_FOUND"})
    snapshot = fixture(scenario)
    snapshot["session_id"] = "demo-" + str(uuid4())
    with _lock:
        run = {
            "owner": request.state.officer["officer_id"],
            "started": monotonic(),
            "snapshot": snapshot,
            "events": [],
        }
        for expired_id in list(_runs):
            if monotonic() - _runs[expired_id]["started"] > RUN_LIFETIME_SECONDS:
                del _runs[expired_id]
        _runs[snapshot["session_id"]] = run
        while len(_runs) > MAX_DEMO_RUNS:
            _runs.popitem(last=False)
        event(run, "SYNTHETIC_SCENARIO_STARTED")
        return deepcopy(snapshot)


@router.post("/runs/{run_id}/recapture")
def recapture(run_id: str, request: Request):
    with _lock:
        run = get_run(run_id, request)
        if run["snapshot"]["demo"]["scenario"] != "poor-capture":
            raise HTTPException(409, detail={"code": "DEMO_RECAPTURE_NOT_APPLICABLE"})
        run["snapshot"] = fixture("poor-capture", recaptured=True) | {
            "session_id": run_id
        }
        event(run, "SYNTHETIC_RECAPTURE_COMPLETED")
        return deepcopy(run["snapshot"])


@router.post("/runs/{run_id}/disposition")
def disposition(run_id: str, payload: OfficerDispositionRequest, request: Request):
    with _lock:
        run = get_run(run_id, request)
        final = run["snapshot"]["final"]
        if (
            payload.decision == "CLEARED"
            and final["decision"] == "REJECT"
            and request.state.officer["role"] != "ADMIN"
        ):
            raise HTTPException(
                403, detail={"code": "SUPERVISOR_REQUIRED_TO_OVERRIDE_REJECT"}
            )
        final["officer_disposition"] = payload.model_dump() | {
            "synthetic": True,
            "officer_username": "SYNTHETIC DEMO OFFICER",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        final["officer_disposition_required"] = False
        event(run, "SYNTHETIC_DISPOSITION_RECORDED")
        return deepcopy(run["snapshot"])


@router.get("/runs/{run_id}/audit")
def audit(run_id: str, request: Request):
    with _lock:
        return {
            "synthetic": True,
            "events": deepcopy(get_run(run_id, request)["events"]),
        }
