from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .config import settings


class SessionNotFoundError(KeyError):
    pass


@dataclass
class ScreeningSession:
    session_id: str
    temp_directory: Path
    document_path: Path
    document_result: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    verifier: Any = None
    face_result: dict | None = None
    duplicate_result: dict | None = None
    final_result: dict | None = None
    lock: RLock = field(default_factory=RLock)

    def status(self) -> str:
        if self.final_result:
            return self.final_result.get("decision", "FINALIZED")
        if self.face_result:
            return "FACE_PROCESSED"
        if self.verifier is not None and getattr(
            self.verifier,
            "session_active",
            False,
        ):
            return "FACE_IN_PROGRESS"
        return "DOCUMENT_ANALYZED"

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status(),
            "document": self.document_result,
            "face": self.face_result,
            "duplicate_identity": self.duplicate_result,
            "final": self.final_result,
            "face_session_active": bool(
                self.verifier is not None
                and getattr(self.verifier, "session_active", False)
            ),
        }


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, ScreeningSession] = {}
        self._lock = RLock()
        settings.runtime_directory.mkdir(parents=True, exist_ok=True)

    def allocate_directory(self) -> Path:
        return Path(tempfile.mkdtemp(
            prefix="screening-",
            dir=settings.runtime_directory,
        ))

    def create(self, temp_directory, document_path, document_result):
        self.cleanup_expired()
        session = ScreeningSession(
            session_id=str(uuid4()),
            temp_directory=Path(temp_directory),
            document_path=Path(document_path),
            document_result=document_result,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ScreeningSession:
        self.cleanup_expired()
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        session.updated_at = datetime.now(timezone.utc)
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        self._dispose(session)
        return True

    def cleanup_expired(self):
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.session_ttl_seconds
        )
        with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if session.updated_at < cutoff
            ]
        for session_id in expired:
            self.delete(session_id)

    def clear(self):
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self.delete(session_id)

    @staticmethod
    def _dispose(session: ScreeningSession):
        if session.verifier is not None:
            session.verifier.close_session()
        if session.temp_directory.exists():
            shutil.rmtree(session.temp_directory, ignore_errors=True)


session_store = SessionStore()
