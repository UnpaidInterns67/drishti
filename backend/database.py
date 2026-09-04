from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS screenings (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    document_result TEXT NOT NULL,
    face_result TEXT,
    duplicate_result TEXT,
    final_result TEXT,
    storage_directory TEXT
);

CREATE TABLE IF NOT EXISTS watchlist_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_number TEXT,
    document_number_normalized TEXT,
    full_name TEXT,
    full_name_normalized TEXT,
    nationality TEXT,
    date_of_birth TEXT,
    reason TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlist_document_number
ON watchlist_entries(document_number_normalized, active);

CREATE INDEX IF NOT EXISTS idx_watchlist_identity
ON watchlist_entries(full_name_normalized, date_of_birth, active);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_session
ON audit_events(session_id, created_at);

CREATE TABLE IF NOT EXISTS face_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_id TEXT NOT NULL,
    document_number TEXT NOT NULL,
    document_number_normalized TEXT NOT NULL,
    full_name TEXT,
    date_of_birth TEXT,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_number_normalized, model_name)
);

CREATE INDEX IF NOT EXISTS idx_face_embeddings_active
ON face_embeddings(active, model_name);

CREATE TABLE IF NOT EXISTS border_crossings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    identity_id TEXT NOT NULL,
    checkpoint_code TEXT NOT NULL,
    movement TEXT NOT NULL CHECK (movement IN ('ENTRY', 'EXIT', 'TRANSIT')),
    lane TEXT,
    document_type TEXT,
    document_number TEXT,
    document_number_normalized TEXT,
    full_name TEXT,
    date_of_birth TEXT,
    nationality TEXT,
    decision TEXT NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0,
    continuity_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_border_crossings_identity
ON border_crossings(identity_id, created_at);

CREATE INDEX IF NOT EXISTS idx_border_crossings_document
ON border_crossings(document_number_normalized, created_at);

CREATE TABLE IF NOT EXISTS officers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OFFICER', 'ADMIN')),
    display_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS officer_sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_hash TEXT NOT NULL,
    officer_id INTEGER NOT NULL,
    active_checkpoint_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (officer_id) REFERENCES officers(id),
    FOREIGN KEY (active_checkpoint_code) REFERENCES checkpoints(code)
);

CREATE INDEX IF NOT EXISTS idx_officer_sessions_expiry
ON officer_sessions(expires_at);

CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    officer_id INTEGER,
    username TEXT,
    source_ip TEXT,
    request_id TEXT,
    event_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (officer_id) REFERENCES officers(id)
);

CREATE INDEX IF NOT EXISTS idx_security_events_created
ON security_events(created_at);

CREATE INDEX IF NOT EXISTS idx_security_events_officer
ON security_events(officer_id, created_at);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None) -> Any:
    return json.loads(value) if value else None


def _normalize_identifier(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _normalize_name(value: str | None) -> str:
    return " ".join((value or "").upper().split())


class SQLiteDatabase:
    """Small repository for persistent screenings, watchlists, and audits."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or settings.database_path)
        self._initialize_lock = RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._initialize_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(SCHEMA)
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(screenings)"
                    ).fetchall()
                }
                if "duplicate_result" not in columns:
                    connection.execute(
                        "ALTER TABLE screenings ADD COLUMN duplicate_result TEXT"
                    )
                if "storage_directory" not in columns:
                    connection.execute(
                        "ALTER TABLE screenings ADD COLUMN storage_directory TEXT"
                    )
                connection.executemany(
                    """
                    INSERT INTO checkpoints (code, name, location, active)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(code) DO NOTHING
                    """,
                    (
                        ("ICP-ATTARI-01", "ICP Attari", "Punjab, India"),
                        ("ICP-PETRAPOLE-02", "ICP Petrapole", "West Bengal, India"),
                        ("ICP-MOREH-03", "ICP Moreh", "Manipur, India"),
                    ),
                )
                connection.execute("PRAGMA optimize")
            self._initialized = True

    def health(self) -> str:
        self.initialize()
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return "ok"

    def create_officer(
        self,
        username: str,
        password_salt: bytes,
        password_hash: bytes,
        display_name: str,
        role: str = "OFFICER",
    ) -> dict:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO officers (
                    username, password_salt, password_hash, role,
                    display_name, active, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_salt = excluded.password_salt,
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    display_name = excluded.display_name,
                    active = 1
                """,
                (
                    username.strip().lower(),
                    sqlite3.Binary(password_salt),
                    sqlite3.Binary(password_hash),
                    role,
                    display_name,
                    _utc_now(),
                ),
            )
        return self.get_officer(username)

    def get_officer(self, username: str) -> dict | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM officers WHERE username = ? AND active = 1",
                (username.strip().lower(),),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "password_salt": bytes(row["password_salt"]),
            "password_hash": bytes(row["password_hash"]),
            "role": row["role"],
            "display_name": row["display_name"],
        }

    def officer_count(self) -> int:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM officers WHERE active = 1"
            ).fetchone()
        return int(row["count"])

    def list_checkpoints(self) -> list[dict]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT code, name, location FROM checkpoints WHERE active = 1 ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def checkpoint_exists(self, code: str) -> bool:
        self.initialize()
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM checkpoints WHERE code = ? AND active = 1",
                (code,),
            ).fetchone() is not None

    def create_officer_session(
        self,
        token_hash: str,
        csrf_hash: str,
        officer_id: int,
        active_checkpoint_code: str,
        expires_at: str,
    ) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM officer_sessions WHERE expires_at <= ?",
                (_utc_now(),),
            )
            connection.execute(
                "DELETE FROM officer_sessions WHERE officer_id = ?",
                (officer_id,),
            )
            connection.execute(
                """
                INSERT INTO officer_sessions (
                    token_hash, csrf_hash, officer_id, active_checkpoint_code,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    csrf_hash,
                    officer_id,
                    active_checkpoint_code,
                    _utc_now(),
                    expires_at,
                ),
            )

    def get_officer_session(self, token_hash: str) -> dict | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT s.token_hash, s.csrf_hash, s.active_checkpoint_code,
                       s.expires_at, o.id AS officer_id, o.username, o.role,
                       o.display_name, c.name AS checkpoint_name,
                       c.location AS checkpoint_location
                FROM officer_sessions s
                JOIN officers o ON o.id = s.officer_id AND o.active = 1
                JOIN checkpoints c ON c.code = s.active_checkpoint_code AND c.active = 1
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, _utc_now()),
            ).fetchone()
        return dict(row) if row else None

    def update_session_checkpoint(self, token_hash: str, checkpoint_code: str) -> bool:
        self.initialize()
        if not self.checkpoint_exists(checkpoint_code):
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE officer_sessions SET active_checkpoint_code = ?
                WHERE token_hash = ? AND expires_at > ?
                """,
                (checkpoint_code, token_hash, _utc_now()),
            )
        return cursor.rowcount == 1

    def delete_officer_session(self, token_hash: str) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM officer_sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def add_security_event(
        self,
        event_type: str,
        *,
        officer_id: int | None = None,
        username: str | None = None,
        source_ip: str | None = None,
        request_id: str | None = None,
        event_data: dict | None = None,
    ) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO security_events (
                    event_type, officer_id, username, source_ip,
                    request_id, event_data, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    officer_id,
                    username,
                    source_ip,
                    request_id,
                    _json_dump(event_data or {}),
                    _utc_now(),
                ),
            )

    def list_security_events(self, limit: int = 100) -> list[dict]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, officer_id, username, source_ip,
                       request_id, event_data, created_at
                FROM security_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "officer_id": row["officer_id"],
                "username": row["username"],
                "source_ip": row["source_ip"],
                "request_id": row["request_id"],
                "data": _json_load(row["event_data"]) or {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_screening(
        self,
        snapshot: dict,
        storage_directory: str | Path | None = None,
    ) -> None:
        self.initialize()
        status = self._screening_status(snapshot)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO screenings (
                    session_id, created_at, updated_at, status,
                    document_result, face_result, duplicate_result, final_result,
                    storage_directory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    document_result = excluded.document_result,
                    face_result = excluded.face_result,
                    duplicate_result = excluded.duplicate_result,
                    final_result = excluded.final_result,
                    storage_directory = COALESCE(
                        excluded.storage_directory,
                        screenings.storage_directory
                    )
                """,
                (
                    snapshot["session_id"],
                    snapshot["created_at"],
                    snapshot["updated_at"],
                    status,
                    _json_dump(snapshot.get("document") or {}),
                    _json_dump(snapshot["face"]) if snapshot.get("face") else None,
                    (
                        _json_dump(snapshot["duplicate_identity"])
                        if snapshot.get("duplicate_identity")
                        else None
                    ),
                    _json_dump(snapshot["final"]) if snapshot.get("final") else None,
                    str(storage_directory) if storage_directory is not None else None,
                ),
            )

    def get_screening(self, session_id: str) -> dict | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM screenings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._screening_from_row(row) if row else None

    def get_screening_storage_directory(self, session_id: str) -> str | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT storage_directory FROM screenings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["storage_directory"] if row else None

    def list_screenings(self, limit: int = 50) -> list[dict]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM screenings
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._screening_from_row(row) for row in rows]

    def delete_screening(self, session_id: str) -> bool:
        self.initialize()
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM screenings WHERE session_id = ?",
                (session_id,),
            )
        return cursor.rowcount > 0

    def purge_screening(self, session_id: str) -> dict:
        """Permanently erase a screening and biometrics enrolled by it."""
        self.initialize()
        with self._connection() as connection:
            border_crossings = connection.execute(
                "DELETE FROM border_crossings WHERE session_id = ?",
                (session_id,),
            ).rowcount
            embeddings = connection.execute(
                "DELETE FROM face_embeddings WHERE identity_id = ?",
                (session_id,),
            ).rowcount
            audits = connection.execute(
                "DELETE FROM audit_events WHERE session_id = ?",
                (session_id,),
            ).rowcount
            screenings = connection.execute(
                "DELETE FROM screenings WHERE session_id = ?",
                (session_id,),
            ).rowcount
        return {
            "screenings": screenings,
            "audit_events": audits,
            "face_embeddings": embeddings,
            "border_crossings": border_crossings,
        }

    def save_border_crossing(self, event: dict) -> dict:
        """Persist one finalized border decision for continuity analysis."""
        self.initialize()
        created_at = event.get("created_at") or _utc_now()
        document_number = event.get("document_number")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO border_crossings (
                    session_id, identity_id, checkpoint_code, movement, lane,
                    document_type, document_number, document_number_normalized,
                    full_name, date_of_birth, nationality, decision, risk_score,
                    continuity_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    identity_id = excluded.identity_id,
                    checkpoint_code = excluded.checkpoint_code,
                    movement = excluded.movement,
                    lane = excluded.lane,
                    document_type = excluded.document_type,
                    document_number = excluded.document_number,
                    document_number_normalized = excluded.document_number_normalized,
                    full_name = excluded.full_name,
                    date_of_birth = excluded.date_of_birth,
                    nationality = excluded.nationality,
                    decision = excluded.decision,
                    risk_score = excluded.risk_score,
                    continuity_status = excluded.continuity_status
                """,
                (
                    event["session_id"],
                    event["identity_id"],
                    event["checkpoint_code"],
                    event["movement"],
                    event.get("lane"),
                    event.get("document_type"),
                    document_number,
                    _normalize_identifier(document_number),
                    event.get("full_name"),
                    event.get("date_of_birth"),
                    event.get("nationality"),
                    event["decision"],
                    float(event.get("risk_score", 0) or 0),
                    event["continuity_status"],
                    created_at,
                ),
            )
        return self.get_border_crossing(event["session_id"])

    def get_border_crossing(self, session_id: str) -> dict | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM border_crossings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._border_crossing_from_row(row) if row else None

    def list_border_crossings(
        self,
        identity_ids: list[str] | None = None,
        document_number: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        self.initialize()
        clauses = []
        parameters: list[Any] = []
        clean_identity_ids = list(dict.fromkeys(
            value for value in (identity_ids or []) if value
        ))
        if clean_identity_ids:
            placeholders = ",".join("?" for _ in clean_identity_ids)
            clauses.append(f"identity_id IN ({placeholders})")
            parameters.extend(clean_identity_ids)
        normalized_document = _normalize_identifier(document_number)
        if normalized_document:
            clauses.append("document_number_normalized = ?")
            parameters.append(normalized_document)
        query = "SELECT * FROM border_crossings"
        if clauses:
            query += " WHERE " + " OR ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        parameters.append(max(1, min(int(limit), 100)))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._border_crossing_from_row(row) for row in rows]

    def add_audit_event(
        self,
        session_id: str,
        event_type: str,
        event_data: dict | None = None,
    ) -> None:
        self.initialize()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    session_id, event_type, event_data, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    _json_dump(event_data or {}),
                    _utc_now(),
                ),
            )

    def get_audit_events(self, session_id: str) -> list[dict]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, event_type, event_data, created_at
                FROM audit_events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "data": _json_load(row["event_data"]) or {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_watchlist_entry(self, entry: dict) -> dict:
        self.initialize()
        created_at = _utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO watchlist_entries (
                    document_number, document_number_normalized,
                    full_name, full_name_normalized, nationality,
                    date_of_birth, reason, metadata, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    entry.get("document_number"),
                    _normalize_identifier(entry.get("document_number")),
                    entry.get("full_name"),
                    _normalize_name(entry.get("full_name")),
                    entry.get("nationality"),
                    entry.get("date_of_birth"),
                    entry["reason"],
                    _json_dump(entry.get("metadata") or {}),
                    created_at,
                ),
            )
            entry_id = cursor.lastrowid
        return self.get_watchlist_entry(entry_id)

    def get_watchlist_entry(self, entry_id: int) -> dict | None:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM watchlist_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
        return self._watchlist_from_row(row) if row else None

    def list_watchlist_entries(self, active_only: bool = True) -> list[dict]:
        self.initialize()
        query = "SELECT * FROM watchlist_entries"
        parameters: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE active = ?"
            parameters = (1,)
        query += " ORDER BY id DESC"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._watchlist_from_row(row) for row in rows]

    def deactivate_watchlist_entry(self, entry_id: int) -> bool:
        self.initialize()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE watchlist_entries SET active = 0
                WHERE id = ? AND active = 1
                """,
                (entry_id,),
            )
        return cursor.rowcount > 0

    def save_face_embedding(
        self,
        identity_id: str,
        document_number: str,
        embedding,
        full_name: str | None = None,
        date_of_birth: str | None = None,
        model_name: str = "sface_2021dec",
    ) -> dict:
        import numpy as np

        self.initialize()
        normalized_document = _normalize_identifier(document_number)
        if not normalized_document:
            raise ValueError("A document number is required for face enrollment")

        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size == 0 or not np.isfinite(vector).all():
            raise ValueError("Face embedding must contain finite values")

        now = _utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO face_embeddings (
                    identity_id, document_number, document_number_normalized,
                    full_name, date_of_birth, model_name, dimensions,
                    embedding, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(document_number_normalized, model_name) DO UPDATE SET
                    identity_id = excluded.identity_id,
                    document_number = excluded.document_number,
                    full_name = excluded.full_name,
                    date_of_birth = excluded.date_of_birth,
                    dimensions = excluded.dimensions,
                    embedding = excluded.embedding,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    identity_id,
                    document_number,
                    normalized_document,
                    full_name,
                    date_of_birth,
                    model_name,
                    int(vector.size),
                    sqlite3.Binary(vector.tobytes()),
                    now,
                    now,
                ),
            )
        return {
            "identity_id": identity_id,
            "document_number": document_number,
            "model_name": model_name,
            "dimensions": int(vector.size),
        }

    def list_face_embeddings(
        self,
        model_name: str = "sface_2021dec",
    ) -> list[dict]:
        import numpy as np

        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT identity_id, document_number, full_name, date_of_birth,
                       dimensions, embedding
                FROM face_embeddings
                WHERE active = 1 AND model_name = ?
                ORDER BY id ASC
                """,
                (model_name,),
            ).fetchall()

        records = []
        for row in rows:
            vector = np.frombuffer(row["embedding"], dtype=np.float32).copy()
            if vector.size != row["dimensions"]:
                continue
            records.append({
                "identity_id": row["identity_id"],
                "document_number": row["document_number"],
                "full_name": row["full_name"],
                "date_of_birth": row["date_of_birth"],
                "embedding": vector,
            })
        return records

    def delete_face_embedding(
        self,
        document_number: str,
        model_name: str = "sface_2021dec",
    ) -> bool:
        self.initialize()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM face_embeddings
                WHERE document_number_normalized = ? AND model_name = ?
                """,
                (_normalize_identifier(document_number), model_name),
            )
        return cursor.rowcount > 0

    def check_watchlist(self, identity: dict) -> dict:
        self.initialize()
        document_number = (
            identity.get("document_number")
            or identity.get("passport_number")
            or identity.get("visa_number")
        )
        full_name = identity.get("name") or identity.get("full_name")
        date_of_birth = identity.get("date_of_birth")
        normalized_document = _normalize_identifier(document_number)
        normalized_name = _normalize_name(full_name)

        clauses = []
        parameters: list[Any] = []
        if normalized_document:
            clauses.append("document_number_normalized = ?")
            parameters.append(normalized_document)
        if normalized_name and date_of_birth:
            clauses.append("(full_name_normalized = ? AND date_of_birth = ?)")
            parameters.extend((normalized_name, date_of_birth))
        if not clauses:
            return {
                "match": False,
                "blacklisted": False,
                "document_blacklisted": False,
                "duplicate_identity": False,
                "metadata": {"source": "sqlite", "matches": []},
            }

        query = (
            "SELECT * FROM watchlist_entries WHERE active = 1 AND ("
            + " OR ".join(clauses)
            + ") ORDER BY id ASC"
        )
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()

        matches = [self._watchlist_from_row(row) for row in rows]
        document_blacklisted = bool(
            normalized_document
            and any(
                row["document_number_normalized"] == normalized_document
                for row in rows
            )
        )
        return {
            "match": bool(matches),
            "blacklisted": bool(matches),
            "document_blacklisted": document_blacklisted,
            "duplicate_identity": False,
            "metadata": {"source": "sqlite", "matches": matches},
        }

    @staticmethod
    def _screening_status(snapshot: dict) -> str:
        final = snapshot.get("final") or {}
        if final:
            return final.get("decision", "FINALIZED")
        if snapshot.get("face"):
            return "FACE_PROCESSED"
        if snapshot.get("face_session_active"):
            return "FACE_IN_PROGRESS"
        return "DOCUMENT_ANALYZED"

    @staticmethod
    def _screening_from_row(row: sqlite3.Row) -> dict:
        return {
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "document": _json_load(row["document_result"]) or {},
            "face": _json_load(row["face_result"]),
            "duplicate_identity": _json_load(row["duplicate_result"]),
            "final": _json_load(row["final_result"]),
            "face_session_active": False,
        }

    @staticmethod
    def _watchlist_from_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "document_number": row["document_number"],
            "full_name": row["full_name"],
            "nationality": row["nationality"],
            "date_of_birth": row["date_of_birth"],
            "reason": row["reason"],
            "metadata": _json_load(row["metadata"]) or {},
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _border_crossing_from_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "identity_id": row["identity_id"],
            "checkpoint_code": row["checkpoint_code"],
            "movement": row["movement"],
            "lane": row["lane"],
            "document_type": row["document_type"],
            "document_number": row["document_number"],
            "full_name": row["full_name"],
            "date_of_birth": row["date_of_birth"],
            "nationality": row["nationality"],
            "decision": row["decision"],
            "risk_score": row["risk_score"],
            "continuity_status": row["continuity_status"],
            "created_at": row["created_at"],
        }


database = SQLiteDatabase()
