from __future__ import annotations

import asyncio
import io
import logging
import shutil
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ai.document_analysis.analyzer import build_document_record
from ai.identity_continuity import build_continuity_assessment
from ai.verification_engine import combine_verification
from ai.secondary_inspection import build_secondary_inspection

from .config import settings
from .database import database
from .auth import SESSION_COOKIE, auth_service
from .ocr_service import ocr_service
from .schemas import (
    ActiveCheckpointUpdate,
    FinalizeRequest,
    HealthResponse,
    OfficerLogin,
    OfficerDispositionRequest,
    WatchlistEntryCreate,
)
from .security import (
    SECURITY_HEADERS,
    SlidingWindowRateLimiter,
    client_ip,
    request_id,
)
from .session_store import SessionNotFoundError, session_store


FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent / "web"
IMAGE_FORMATS = {
    "JPEG": (".jpg", {"image/jpeg", "image/jpg"}),
    "PNG": (".png", {"image/png"}),
    "WEBP": (".webp", {"image/webp"}),
    "TIFF": (".tiff", {"image/tiff"}),
}
logger = logging.getLogger("drishti.security")
api_limiter = SlidingWindowRateLimiter(
    settings.api_rate_limit, settings.api_rate_window_seconds
)
login_limiter = SlidingWindowRateLimiter(
    settings.login_rate_limit, settings.login_rate_window_seconds
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_startup()
    settings.runtime_directory.mkdir(parents=True, exist_ok=True)
    database.initialize()
    auth_service.bootstrap()
    if settings.is_production and database.officer_count() == 0:
        raise RuntimeError("Production requires at least one active officer")
    yield
    session_store.clear()


app = FastAPI(
    title="Identity Verification API",
    version="1.0.0",
    description="AI-assisted identity document, tampering, and face screening.",
    lifespan=lifespan,
    debug=False,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(settings.allowed_hosts),
    www_redirect=False,
)
if settings.require_https:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def enforce_officer_authentication(request: Request, call_next):
    path = request.url.path
    current_request_id = request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = current_request_id
    peer_ip = client_ip(request.client)
    request.state.client_ip = peer_ip
    protected = path.startswith(settings.api_prefix)
    public_api_paths = {f"{settings.api_prefix}/auth/login"}
    if protected:
        limiter = login_limiter if path in public_api_paths else api_limiter
        rate = limiter.check(f"{path if path in public_api_paths else 'api'}:{peer_ip}")
        if not rate.allowed:
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": {"code": "RATE_LIMIT_EXCEEDED"}},
                headers={"Retry-After": str(rate.retry_after)},
            )
            return _secure_response(response, path, current_request_id)
    content_length = request.headers.get("content-length")
    maximum_request_bytes = settings.max_upload_bytes * 2 + 1024 * 1024
    if content_length and content_length.isdigit() and int(content_length) > maximum_request_bytes:
        response = JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": {"code": "REQUEST_TOO_LARGE"}},
        )
        return _secure_response(response, path, current_request_id)
    if protected and path not in public_api_paths and request.method != "OPTIONS":
        session = auth_service.session_by_token(
            request.cookies.get(SESSION_COOKIE)
        )
        if session is None:
            response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": {"code": "OFFICER_AUTHENTICATION_REQUIRED"}},
            )
            return _secure_response(response, path, current_request_id)
        request.state.officer = session
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not auth_service.valid_csrf(
                session, request.headers.get("X-CSRF-Token")
            ):
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": {"code": "CSRF_VALIDATION_FAILED"}},
                )
                return _secure_response(response, path, current_request_id)
    response = await call_next(request)
    return _secure_response(response, path, current_request_id)


def _secure_response(response: Response, path: str, current_request_id: str) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers["X-Request-ID"] = current_request_id
    if settings.require_https:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if path == "/" or path.startswith(settings.api_prefix):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
    return response


def _security_event(request: Request, event_type: str, **data) -> None:
    officer = getattr(request.state, "officer", None) or {}
    try:
        database.add_security_event(
            event_type,
            officer_id=officer.get("officer_id"),
            username=officer.get("username") or data.pop("username", None),
            source_ip=getattr(request.state, "client_ip", None),
            request_id=getattr(request.state, "request_id", None),
            event_data=data,
        )
    except Exception:
        logger.exception("Unable to persist security event %s", event_type)


def _require_admin(request: Request) -> dict:
    try:
        return auth_service.require_role(request, "ADMIN")
    except HTTPException:
        _security_event(request, "AUTHORIZATION_DENIED", required_role="ADMIN")
        raise


def _http_session(session_id: str):
    try:
        return session_store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "session_id": session_id},
        ) from exc


def _stored_screening(session_id: str) -> dict:
    try:
        return session_store.get(session_id).snapshot()
    except SessionNotFoundError:
        stored = database.get_screening(session_id)
        if stored is not None:
            return stored
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "session_id": session_id},
        )


def _document_identity(document_result: dict) -> dict:
    documents = (document_result or {}).get("documents") or []
    if not documents:
        return {}
    return documents[0].get("identity") or {}


def _document_number(identity: dict) -> str | None:
    return (
        identity.get("document_number")
        or identity.get("passport_number")
        or identity.get("visa_number")
    )


def _merge_watchlist_results(database_result: dict, supplied_result: dict) -> dict:
    boolean_fields = (
        "match",
        "blacklisted",
        "document_blacklisted",
        "duplicate_identity",
    )
    merged = {
        field: bool(database_result.get(field) or supplied_result.get(field))
        for field in boolean_fields
    }
    merged["metadata"] = {
        "database": database_result.get("metadata", {}),
        "supplied": supplied_result.get("metadata", {}),
    }
    return merged


async def _read_image(upload: UploadFile) -> tuple[bytes, str]:
    if upload.content_type not in {
        "image/jpeg", "image/jpg", "image/png", "image/webp", "image/tiff"
    }:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_MEDIA_TYPE"},
        )
    data = await upload.read(settings.max_upload_bytes + 1)
    await upload.close()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_UPLOAD"},
        )
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "UPLOAD_TOO_LARGE"},
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as candidate:
                image_format = candidate.format
                width, height = candidate.size
                candidate.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "IMAGE_DIMENSIONS_TOO_LARGE"},
        )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_IMAGE"},
        ) from exc
    if width * height > settings.max_image_pixels:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "IMAGE_DIMENSIONS_TOO_LARGE"},
        )
    format_configuration = IMAGE_FORMATS.get(image_format or "")
    if not format_configuration:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_IMAGE_FORMAT"},
        )
    suffix, expected_content_types = format_configuration
    if upload.content_type not in expected_content_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "IMAGE_CONTENT_TYPE_MISMATCH"},
        )
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_IMAGE"},
        )
    return data, suffix


def _decode_frame(data: bytes):
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Unable to decode frame")
    return frame


def _new_verifier():
    from ai.face_verification import IdentityVerifier

    return IdentityVerifier()


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    return {
        "status": "ok",
        "service": "identity-verification",
        "version": "1.0.0",
        "database": database.health(),
    }


def _public_officer(session: dict) -> dict:
    return {
        "id": session["officer_id"],
        "username": session["username"],
        "display_name": session["display_name"],
        "role": session["role"],
        "active_checkpoint": {
            "code": session["active_checkpoint_code"],
            "name": session["checkpoint_name"],
            "location": session["checkpoint_location"],
        },
    }


@app.post(f"{settings.api_prefix}/auth/login", tags=["officer-auth"])
def officer_login(payload: OfficerLogin, request: Request, response: Response):
    login = auth_service.login(payload.username, payload.password)
    if login is None:
        _security_event(
            request,
            "LOGIN_FAILED",
            username=payload.username,
            reason="INVALID_CREDENTIALS",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_OFFICER_CREDENTIALS"},
        )
    request.state.officer = login["officer"]
    _security_event(request, "LOGIN_SUCCEEDED")
    response.set_cookie(
        SESSION_COOKIE,
        login["token"],
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {
        "officer": _public_officer(login["officer"]),
        "csrf_token": login["csrf_token"],
        "expires_at": login["expires_at"],
        "checkpoints": database.list_checkpoints(),
    }


@app.get(f"{settings.api_prefix}/auth/me", tags=["officer-auth"])
def officer_session(request: Request):
    return {
        "officer": _public_officer(auth_service.require_session(request)),
        "checkpoints": database.list_checkpoints(),
    }


@app.post(f"{settings.api_prefix}/auth/active-checkpoint", tags=["officer-auth"])
def change_active_checkpoint(payload: ActiveCheckpointUpdate, request: Request):
    previous = auth_service.require_session(request)["active_checkpoint_code"]
    session = auth_service.change_checkpoint(request, payload.checkpoint_code)
    _security_event(
        request,
        "ACTIVE_CHECKPOINT_CHANGED",
        previous_checkpoint=previous,
        active_checkpoint=payload.checkpoint_code,
    )
    return {"officer": _public_officer(session)}


@app.post(f"{settings.api_prefix}/auth/logout", status_code=204, tags=["officer-auth"])
def officer_logout(request: Request):
    _security_event(request, "LOGOUT")
    auth_service.logout(request)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.post(f"{settings.api_prefix}/warmup", tags=["system"])
async def warmup_models():
    """Preload heavyweight inference models before the first screening."""
    return await run_in_threadpool(ocr_service.warmup)


@app.post(
    f"{settings.api_prefix}/screenings",
    status_code=status.HTTP_201_CREATED,
    tags=["screenings"],
)
async def create_screening(
    document: Annotated[UploadFile, File(description="Identity document image")],
):
    data, suffix = await _read_image(document)
    temp_directory = session_store.allocate_directory()
    document_path = temp_directory / f"document{suffix}"

    try:
        await run_in_threadpool(document_path.write_bytes, data)
        from ai.image_forensics.forensic_engine import analyze_image_forensics

        ocr_items, forensic_result = await asyncio.gather(
            run_in_threadpool(ocr_service.extract, document_path),
            run_in_threadpool(analyze_image_forensics, document_path),
        )
        result = await run_in_threadpool(
            build_document_record,
            ocr_items,
            document_path,
            forensic_result,
        )
    except Exception as exc:
        logger.exception("Document analysis failed")
        shutil.rmtree(temp_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "DOCUMENT_ANALYSIS_FAILED"},
        ) from exc

    session = session_store.create(temp_directory, document_path, result)
    try:
        await run_in_threadpool(
            database.save_screening,
            session.snapshot(),
            temp_directory,
        )
        await run_in_threadpool(
            database.add_audit_event,
            session.session_id,
            "DOCUMENT_ANALYZED",
            {
                "document_type": result.get("classification", {}).get(
                    "document_type"
                ),
                "document_count": result.get("document_count", 0),
            },
        )
    except Exception as exc:
        logger.exception("Screening persistence failed")
        session_store.delete(session.session_id)
        database.delete_screening(session.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PERSISTENCE_FAILED"},
        ) from exc

    return session.snapshot()


@app.post(
    f"{settings.api_prefix}/screenings/aadhaar-card",
    status_code=status.HTTP_201_CREATED,
    tags=["screenings"],
)
async def create_aadhaar_card_screening(
    front: Annotated[UploadFile, File(description="Aadhaar front-side image")],
    back: Annotated[UploadFile, File(description="Aadhaar back-side image containing Secure QR")],
):
    """Verify a physical Aadhaar using its front and UIDAI-signed back QR."""
    front_upload, back_upload = await asyncio.gather(
        _read_image(front), _read_image(back)
    )
    front_data, front_suffix = front_upload
    back_data, back_suffix = back_upload
    temp_directory = session_store.allocate_directory()
    front_path = temp_directory / f"aadhaar_front{front_suffix}"
    back_path = temp_directory / f"aadhaar_back{back_suffix}"

    from ai.document_analysis.aadhaar import analyze_aadhaar
    from ai.document_analysis.secure_qr import (
        SecureQrError,
        build_secure_qr_document,
        decode_secure_qr,
        read_qr_text,
    )

    def verify_back_qr():
        return decode_secure_qr(
            read_qr_text(back_path),
            settings.uidai_certificate_directory,
        )

    try:
        await asyncio.gather(
            run_in_threadpool(front_path.write_bytes, front_data),
            run_in_threadpool(back_path.write_bytes, back_data),
        )
        front_ocr, verification = await asyncio.gather(
            run_in_threadpool(ocr_service.extract, front_path),
            run_in_threadpool(verify_back_qr),
        )
        front_identity = analyze_aadhaar(front_ocr)["fields"]
        photo = verification["fields"].pop("photo")
        portrait_path = temp_directory / "uidai_secure_qr_portrait.png"
        try:
            portrait = Image.open(io.BytesIO(photo)).convert("RGB")
            await run_in_threadpool(portrait.save, portrait_path, "PNG")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise SecureQrError(
                "AADHAAR_SECURE_QR_PHOTO_INVALID",
                "The photograph embedded in the signed Secure QR could not be decoded.",
            ) from exc
        from ai.face_verification.document_portrait import compare_document_portraits

        portrait_cross_check = await run_in_threadpool(
            compare_document_portraits,
            front_path,
            portrait_path,
        )
        result = build_secure_qr_document(
            verification,
            front_identity,
            portrait_cross_check,
        )
    except SecureQrError as exc:
        shutil.rmtree(temp_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Aadhaar card analysis failed")
        shutil.rmtree(temp_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "AADHAAR_CARD_ANALYSIS_FAILED"},
        ) from exc

    session = session_store.create(temp_directory, portrait_path, result)
    try:
        await run_in_threadpool(database.save_screening, session.snapshot(), temp_directory)
        document = result["documents"][0]
        await run_in_threadpool(
            database.add_audit_event,
            session.session_id,
            "UIDAI_SECURE_QR_VERIFIED",
            {
                "signature_valid": True,
                "front_cross_check_valid": document["cross_validation"]["valid"],
                "portrait_cross_check": document["cross_validation"].get("portrait"),
                "certificate_fingerprint": document["issuer_verification"]["certificate"]["sha256_fingerprint"],
            },
        )
    except Exception as exc:
        logger.exception("Aadhaar card persistence failed")
        session_store.delete(session.session_id)
        database.purge_screening(session.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "AADHAAR_CARD_PERSISTENCE_FAILED"},
        ) from exc
    return session.snapshot()


@app.post(
    f"{settings.api_prefix}/screenings/{{session_id}}/face/start",
    tags=["face-verification"],
)
async def start_face_verification(session_id: str):
    session = _http_session(session_id)

    def start():
        with session.lock:
            if session.verifier is not None:
                session.verifier.close_session()
            session.verifier = _new_verifier()
            result = session.verifier.start_session(session.document_path)
            if not result.get("started", False):
                session.verifier.close_session()
                session.verifier = None
                session.duplicate_result = None
            else:
                from ai.face_verification import find_duplicate_identities

                identity = _document_identity(session.document_result)
                session.duplicate_result = find_duplicate_identities(
                    session.verifier.id_embedding,
                    database.list_face_embeddings(),
                    document_number=_document_number(identity),
                    full_name=identity.get("name") or identity.get("full_name"),
                    date_of_birth=identity.get("date_of_birth"),
                    threshold=settings.duplicate_face_threshold,
                )
            database.save_screening(session.snapshot())
            database.add_audit_event(
                session_id,
                "FACE_SESSION_STARTED" if result.get("started") else "FACE_SESSION_FAILED",
                result,
            )
            if session.duplicate_result is not None:
                database.add_audit_event(
                    session_id,
                    "DUPLICATE_IDENTITY_CHECKED",
                    {
                        "duplicate_identity": session.duplicate_result.get(
                            "duplicate_identity",
                            False,
                        ),
                        "match_count": len(
                            session.duplicate_result.get("matches", [])
                        ),
                        "same_identity_count": len(
                            session.duplicate_result.get("same_identity_matches", [])
                        ),
                        "conflict_count": len(
                            session.duplicate_result.get("duplicate_matches", [])
                        ),
                        "threshold": session.duplicate_result.get("threshold"),
                    },
                )
            return result

    result = await run_in_threadpool(start)
    if not result.get("started", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "FACE_SESSION_NOT_STARTED", "result": result},
        )
    return {
        "session_id": session_id,
        "face": result,
        "duplicate_identity": session.duplicate_result,
    }


@app.post(
    f"{settings.api_prefix}/screenings/{{session_id}}/face/frame",
    tags=["face-verification"],
)
async def process_face_frame(
    session_id: str,
    frame: Annotated[UploadFile, File(description="Current webcam frame")],
    mirrored: Annotated[bool, Query()] = False,
):
    session = _http_session(session_id)
    data, _suffix = await _read_image(frame)

    def process():
        with session.lock:
            if session.verifier is None or not session.verifier.session_active:
                raise RuntimeError("Face session is not active")
            decoded = _decode_frame(data)
            if mirrored:
                decoded = cv2.flip(decoded, 1)
            result = session.verifier.process_frame(decoded)
            if "verification_passed" in result:
                session.face_result = result
                database.add_audit_event(
                    session_id,
                    "FACE_VERIFICATION_COMPLETED",
                    {
                        "verification_passed": result.get("verification_passed"),
                        "face_match": result.get("face_match"),
                        "liveness_passed": result.get("liveness_passed"),
                    },
                )
            database.save_screening(session.snapshot())
            return result

    try:
        result = await run_in_threadpool(process)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FACE_SESSION_NOT_ACTIVE"},
        ) from exc
    return {"session_id": session_id, "face": result}


@app.post(
    f"{settings.api_prefix}/screenings/{{session_id}}/finalize",
    tags=["screenings"],
)
async def finalize_screening(
    session_id: str,
    payload: FinalizeRequest,
    http_request: Request,
):
    session = _http_session(session_id)
    officer = auth_service.require_session(http_request)
    border_context = payload.border_context.model_dump()
    # The active post is trusted session state. A browser cannot attribute a
    # crossing to another checkpoint by changing the request payload.
    border_context["checkpoint_code"] = officer["active_checkpoint_code"]

    def finalize():
        with session.lock:
            if session.face_result is None and not payload.allow_incomplete_face:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "FACE_RESULT_REQUIRED"},
                )
            database_watchlist = database.check_watchlist(
                _document_identity(session.document_result)
            )
            duplicate_result = session.duplicate_result or {
                "duplicate_identity": False,
                "matches": [],
                "duplicate_matches": [],
                "threshold": settings.duplicate_face_threshold,
            }
            database_watchlist["duplicate_identity"] = bool(
                duplicate_result.get("duplicate_identity")
            )
            database_watchlist.setdefault("metadata", {})[
                "duplicate_identity"
            ] = duplicate_result
            watchlist_result = _merge_watchlist_results(
                database_watchlist,
                payload.watchlist.model_dump(),
            )
            identity = _document_identity(session.document_result)
            document_number = _document_number(identity)
            documents = (session.document_result or {}).get("documents") or []
            document_type = (
                documents[0].get("document_type") if documents else None
            )
            biometric_matches = duplicate_result.get("matches") or []
            linked_identity_ids = list(dict.fromkeys(
                match.get("identity_id")
                for match in biometric_matches
                if match.get("identity_id")
            ))
            continuity_identity_id = (
                linked_identity_ids[0] if linked_identity_ids else session_id
            )
            prior_crossings = database.list_border_crossings(
                identity_ids=linked_identity_ids,
                document_number=document_number,
                limit=20,
            )
            continuity = build_continuity_assessment(
                identity,
                document_type,
                duplicate_result,
                prior_crossings,
                border_context,
            )
            session.final_result = combine_verification(
                session.document_result,
                session.face_result or {},
                watchlist_result,
            )
            session.final_result["continuity"] = continuity
            session.final_result["border_context"] = border_context
            session.final_result["secondary_inspection"] = (
                build_secondary_inspection(session.final_result, continuity)
            )

            should_enroll = bool(
                session.final_result.get("decision") == "APPROVE"
                and session.face_result
                and session.face_result.get("face_match")
                and session.face_result.get("liveness_passed")
                and session.verifier is not None
                and session.verifier.id_embedding is not None
                and document_number
                and not identity.get("aadhaar_masked", False)
            )
            if should_enroll:
                same_identity_matches = duplicate_result.get(
                    "same_identity_matches",
                    [],
                )
                linked_identity_id = next(
                    (
                        match.get("identity_id")
                        for match in same_identity_matches
                        if match.get("identity_id")
                    ),
                    None,
                )
                enrollment = database.save_face_embedding(
                    # Multiple credentials belonging to one person share one
                    # canonical identity id instead of becoming separate people.
                    identity_id=linked_identity_id or session_id,
                    document_number=document_number,
                    embedding=session.verifier.id_embedding,
                    full_name=identity.get("name") or identity.get("full_name"),
                    date_of_birth=identity.get("date_of_birth"),
                )
                enrollment["linked_to_existing_identity"] = bool(linked_identity_id)
                database.add_audit_event(
                    session_id,
                    "FACE_IDENTITY_ENROLLED",
                    enrollment,
                )
            snapshot = session.snapshot()
            database.save_screening(snapshot)
            database.save_border_crossing({
                "session_id": session_id,
                "identity_id": continuity_identity_id,
                "checkpoint_code": border_context["checkpoint_code"],
                "movement": border_context["movement"],
                "lane": border_context.get("lane"),
                "document_type": document_type,
                "document_number": document_number,
                "full_name": identity.get("name") or identity.get("full_name"),
                "date_of_birth": identity.get("date_of_birth"),
                "nationality": identity.get("nationality"),
                "decision": session.final_result.get("decision"),
                "risk_score": session.final_result.get("risk_score", 0),
                "continuity_status": continuity["status"],
            })
            database.add_audit_event(
                session_id,
                "SCREENING_FINALIZED",
                {
                    "decision": session.final_result.get("decision"),
                    "risk_score": session.final_result.get("risk_score"),
                    "watchlist_match": watchlist_result.get("match", False),
                    "continuity_status": continuity["status"],
                    "checkpoint_code": border_context["checkpoint_code"],
                    "movement": border_context["movement"],
                    "officer_id": officer["officer_id"],
                    "officer_username": officer["username"],
                    "inspection_status": session.final_result[
                        "secondary_inspection"
                    ]["status"],
                    "inspection_action": session.final_result[
                        "secondary_inspection"
                    ]["primary_action"]["code"],
                },
            )
            return snapshot

    return await run_in_threadpool(finalize)


@app.post(
    f"{settings.api_prefix}/screenings/{{session_id}}/disposition",
    tags=["screenings"],
)
async def record_officer_disposition(
    session_id: str,
    payload: OfficerDispositionRequest,
    http_request: Request,
):
    """Record the accountable human outcome after automated triage."""
    session = _http_session(session_id)
    officer = auth_service.require_session(http_request)

    def record():
        with session.lock:
            if session.final_result is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "SCREENING_MUST_BE_FINALIZED"},
                )
            if (
                payload.decision == "CLEARED"
                and session.final_result.get("decision") == "REJECT"
                and officer.get("role") != "ADMIN"
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "SUPERVISOR_REQUIRED_TO_OVERRIDE_REJECT",
                        "message": "A supervisor must authorize clearance against a critical automated alert.",
                    },
                )

            previous = session.final_result.get("officer_disposition")
            disposition = {
                "decision": payload.decision,
                "reason_code": payload.reason_code,
                "notes": payload.notes,
                "officer_id": officer["officer_id"],
                "officer_username": officer["username"],
                "officer_role": officer["role"],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "overrides_automated_triage": (
                    (payload.decision == "CLEARED" and session.final_result.get("decision") != "APPROVE")
                    or (payload.decision == "DENIED" and session.final_result.get("decision") != "REJECT")
                ),
            }
            session.final_result["officer_disposition"] = disposition
            session.final_result["officer_disposition_required"] = False
            database.save_screening(session.snapshot())
            database.add_audit_event(
                session_id,
                "OFFICER_DISPOSITION_RECORDED",
                {
                    **disposition,
                    "notes": "[RECORDED]" if disposition.get("notes") else None,
                    "previous_decision": previous.get("decision") if previous else None,
                    "automated_triage": session.final_result.get("decision"),
                },
            )
            return session.snapshot()

    snapshot = await run_in_threadpool(record)
    _security_event(
        http_request,
        "OFFICER_DISPOSITION_RECORDED",
        session_id=session_id,
        decision=payload.decision,
        reason_code=payload.reason_code,
    )
    return snapshot


@app.get(f"{settings.api_prefix}/screenings", tags=["screenings"])
def list_screenings(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    _require_admin(request)
    return {"screenings": database.list_screenings(limit), "limit": limit}


@app.get(f"{settings.api_prefix}/border-crossings", tags=["border-operations"])
def list_border_crossings(
    request: Request,
    identity_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    _require_admin(request)
    return {
        "crossings": database.list_border_crossings(
            identity_ids=[identity_id] if identity_id else None,
            limit=limit,
        ),
        "limit": limit,
    }


@app.get(
    f"{settings.api_prefix}/screenings/{{session_id}}",
    tags=["screenings"],
)
def get_screening(session_id: str, request: Request):
    _require_admin(request)
    return _stored_screening(session_id)


@app.get(
    f"{settings.api_prefix}/screenings/{{session_id}}/audit",
    tags=["screenings"],
)
def get_screening_audit(session_id: str, request: Request):
    _require_admin(request)
    events = database.get_audit_events(session_id)
    if database.get_screening(session_id) is None and not events:
        _stored_screening(session_id)
    return {
        "session_id": session_id,
        "events": events,
    }


@app.delete(
    f"{settings.api_prefix}/screenings/{{session_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["screenings"],
)
def delete_screening(session_id: str, request: Request):
    _require_admin(request)
    stored = database.get_screening(session_id)
    stored_directory = database.get_screening_storage_directory(session_id)
    in_memory_deleted = session_store.delete(session_id)
    if not in_memory_deleted and stored is None:
        _stored_screening(session_id)

    # A restarted process no longer has the in-memory Session object needed by
    # SessionStore.delete(). Recover the upload directory from persisted
    # forensic metadata and remove it only when it is a screening directory
    # safely contained by the configured runtime root.
    if not in_memory_deleted and stored:
        try:
            image_path = stored_directory or (
                stored.get("document", {}).get("documents", [{}])[0]
                .get("forensics", {}).get("image", {}).get("path")
            )
            runtime_root = settings.runtime_directory.resolve()
            candidate = Path(image_path).resolve()
            upload_directory = candidate if stored_directory else candidate.parent
            upload_directory.relative_to(runtime_root)
            if upload_directory.name.startswith("screening-"):
                shutil.rmtree(upload_directory, ignore_errors=True)
        except (AttributeError, IndexError, TypeError, ValueError):
            pass

    database.purge_screening(session_id)
    return None


@app.post(
    f"{settings.api_prefix}/watchlist",
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist"],
)
def create_watchlist_entry(entry: WatchlistEntryCreate, request: Request):
    _require_admin(request)
    if not entry.document_number and not (
        entry.full_name and entry.date_of_birth
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "WATCHLIST_IDENTITY_REQUIRED",
                "message": (
                    "Provide a document number or both full name and date of birth"
                ),
            },
        )
    return database.create_watchlist_entry(entry.model_dump())


@app.get(f"{settings.api_prefix}/watchlist", tags=["watchlist"])
def list_watchlist_entries(request: Request, active_only: bool = True):
    _require_admin(request)
    return {
        "entries": database.list_watchlist_entries(active_only=active_only)
    }


@app.delete(
    f"{settings.api_prefix}/watchlist/{{entry_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["watchlist"],
)
def deactivate_watchlist_entry(entry_id: int, request: Request):
    _require_admin(request)
    if not database.deactivate_watchlist_entry(entry_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WATCHLIST_ENTRY_NOT_FOUND", "entry_id": entry_id},
        )
    return None


@app.get(f"{settings.api_prefix}/security/events", tags=["security"])
def list_security_events(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    _require_admin(request)
    return {"events": database.list_security_events(limit), "limit": limit}


# Keep the UI routes last so they can never shadow the API endpoints above.
if FRONTEND_DIRECTORY.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIRECTORY),
        name="frontend-assets",
    )

    @app.get("/", include_in_schema=False)
    def frontend_index():
        return FileResponse(FRONTEND_DIRECTORY / "index.html")
