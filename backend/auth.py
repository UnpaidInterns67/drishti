"""Persistent officer authentication and checkpoint-scoped sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status

from .config import settings
from .database import database


SESSION_COOKIE = (
    "__Host-drishti_session"
    if settings.auth_cookie_secure
    else "drishti_officer_session"
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


class OfficerAuthService:
    def bootstrap(self) -> None:
        username = settings.bootstrap_officer_username
        password = settings.bootstrap_officer_password
        if not username and not password:
            return
        if not username or not password or len(password) < 14:
            raise RuntimeError(
                "BOOTSTRAP_OFFICER_USERNAME and a password of at least 14 "
                "characters are required together"
            )
        if database.get_officer(username):
            return
        salt = secrets.token_bytes(16)
        database.create_officer(
            username,
            salt,
            _password_hash(password, salt),
            display_name=username,
            role="ADMIN",
        )

    def create_officer_for_test(
        self,
        username: str,
        password: str,
        display_name: str = "Test Officer",
        role: str = "ADMIN",
    ) -> dict:
        salt = secrets.token_bytes(16)
        return database.create_officer(
            username,
            salt,
            _password_hash(password, salt),
            display_name,
            role,
        )

    def login(self, username: str, password: str) -> dict | None:
        officer = database.get_officer(username)
        if not officer:
            # Perform equivalent work so unknown usernames do not return faster.
            _password_hash(password, b"\0" * 16)
            return None
        candidate = _password_hash(password, officer["password_salt"])
        if not hmac.compare_digest(candidate, officer["password_hash"]):
            return None
        checkpoints = database.list_checkpoints()
        if not checkpoints:
            raise RuntimeError("No active border checkpoints are configured")
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.auth_session_ttl_seconds
        )
        database.create_officer_session(
            _digest(token),
            _digest(csrf_token),
            officer["id"],
            checkpoints[0]["code"],
            expires_at.isoformat(),
        )
        return {
            "token": token,
            "csrf_token": csrf_token,
            "expires_at": expires_at.isoformat(),
            "officer": self.session_by_token(token),
        }

    def session_by_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        return database.get_officer_session(_digest(token))

    def require_session(self, request: Request) -> dict:
        session = getattr(request.state, "officer", None)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "OFFICER_AUTHENTICATION_REQUIRED"},
            )
        return session

    def require_role(self, request: Request, *roles: str) -> dict:
        session = self.require_session(request)
        if session["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "INSUFFICIENT_OFFICER_PERMISSIONS"},
            )
        return session

    def valid_csrf(self, session: dict, supplied: str | None) -> bool:
        return bool(
            supplied
            and hmac.compare_digest(session["csrf_hash"], _digest(supplied))
        )

    def change_checkpoint(self, request: Request, checkpoint_code: str) -> dict:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or not database.update_session_checkpoint(
            _digest(token), checkpoint_code
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "CHECKPOINT_NOT_AVAILABLE"},
            )
        return self.session_by_token(token)

    def logout(self, request: Request) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            database.delete_officer_session(_digest(token))


auth_service = OfficerAuthService()
