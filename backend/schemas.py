from typing import Any, Literal

import json
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if CONTROL_CHARACTERS.search(clean):
        raise ValueError("control characters are not allowed")
    return clean


class WatchlistResult(StrictRequestModel):
    match: bool = False
    blacklisted: bool = False
    document_blacklisted: bool = False
    duplicate_identity: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BorderContext(StrictRequestModel):
    checkpoint_code: str = Field(
        default="DEMO-ICP", min_length=2, max_length=50, pattern=r"^[A-Z0-9-]+$"
    )
    movement: Literal["ENTRY", "EXIT", "TRANSIT"] = "ENTRY"
    lane: str | None = Field(default=None, max_length=30, pattern=r"^[A-Za-z0-9 _-]+$")


class OfficerLogin(StrictRequestModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class ActiveCheckpointUpdate(StrictRequestModel):
    checkpoint_code: str = Field(
        min_length=2, max_length=50, pattern=r"^[A-Z0-9-]+$"
    )


class FinalizeRequest(StrictRequestModel):
    watchlist: WatchlistResult = Field(default_factory=WatchlistResult)
    allow_incomplete_face: bool = False
    border_context: BorderContext = Field(default_factory=BorderContext)


class OfficerDispositionRequest(StrictRequestModel):
    decision: Literal["CLEARED", "REFERRED", "DENIED"]
    reason_code: Literal[
        "AUTOMATED_CHECKS_CLEAR",
        "DOCUMENT_EXAMINATION",
        "WATCHLIST_ESCALATION",
        "BIOMETRIC_MISMATCH",
        "IDENTITY_CONFLICT",
        "SUPERVISOR_DIRECTION",
        "INSUFFICIENT_EVIDENCE",
        "OTHER",
    ]
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @model_validator(mode="after")
    def require_consistent_reason(self):
        if (
            self.reason_code == "AUTOMATED_CHECKS_CLEAR"
            and self.decision != "CLEARED"
        ):
            raise ValueError(
                "AUTOMATED_CHECKS_CLEAR can only support a CLEARED disposition"
            )
        if self.reason_code == "OTHER" and not self.notes:
            raise ValueError("Officer notes are required when reason_code is OTHER")
        return self


class WatchlistEntryCreate(StrictRequestModel):
    document_number: str | None = Field(default=None, max_length=64)
    full_name: str | None = Field(default=None, max_length=160)
    nationality: str | None = Field(default=None, max_length=64)
    date_of_birth: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    reason: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "document_number", "full_name", "nationality", "date_of_birth", "reason"
    )
    @classmethod
    def clean_text_fields(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @model_validator(mode="after")
    def limit_metadata(self):
        if len(json.dumps(self.metadata, ensure_ascii=False)) > 8192:
            raise ValueError("metadata is too large")
        return self


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: str
