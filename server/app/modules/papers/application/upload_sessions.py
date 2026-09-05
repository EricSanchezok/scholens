"""Durable staging sessions for direct-to-object-storage PDF uploads."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.papers.domain import MAX_PDF_BYTES, MAX_PDF_SIZE_MB
from app.shared.application import Actor, Clock
from app.shared.domain import AppError, FailureKind
from pydantic import BaseModel, ConfigDict, Field, field_validator

UPLOAD_SESSION_TTL = timedelta(hours=24)
UPLOAD_URL_TTL_SECONDS = 900
UPLOAD_CLAIM_TTL = timedelta(minutes=5)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PreparePaperUploadRequest(BaseModel):
    """Metadata known locally before PDF bytes leave the user's computer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    filename: str = Field(
        min_length=1,
        max_length=255,
        description=(
            "Plain local PDF filename without directory components. Paths remain on "
            "the client and must never be sent to Scholens."
        ),
    )
    size_bytes: int = Field(
        gt=0,
        le=MAX_PDF_BYTES,
        description=(
            f"Exact local file size in bytes; the maximum is {MAX_PDF_SIZE_MB} MiB "
            f"({MAX_PDF_BYTES} bytes). Compress or optimize a copy before preparing "
            "an upload when the original is larger."
        ),
    )
    sha256: str = Field(
        min_length=64,
        max_length=64,
        description=(
            "Lowercase hexadecimal SHA-256 of the exact PDF bytes. Scholens verifies "
            "this before ingestion and duplicate resolution."
        ),
    )
    project_id: UUID | None = Field(
        default=None,
        description=(
            "Optional immutable destination Project UUID. Omit it for personal-Library "
            "ingestion."
        ),
    )
    add_to_library: bool = Field(
        default_factory=lambda: True,
        description=(
            "When true and a Project is targeted, the completed paper is also "
            "added to the caller's personal Library. Set false to keep it "
            "Project-only. Requires project_id."
        ),
    )
    upload_id: UUID | None = Field(
        default=None,
        description=(
            "Existing prepared upload UUID when only its short-lived PUT URL expired. "
            "The filename, size, checksum, and Project must remain identical."
        ),
    )

    @field_validator("filename")
    @classmethod
    def require_plain_pdf_filename(cls, value: str) -> str:
        if PurePath(value).name != value or not value.casefold().endswith(".pdf"):
            raise ValueError("filename must be a plain PDF filename without a path")
        return value

    @field_validator("sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        normalized = value.casefold()
        if _SHA256_PATTERN.fullmatch(normalized) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return normalized


class PreparePaperUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID = Field(description="Durable staging UUID used by ingest_paper.")
    upload_url: str = Field(description="Short-lived direct object-storage PUT URL.")
    method: str = Field(default="PUT", description="Required HTTP upload method.")
    headers: dict[str, str] = Field(
        description="Exact request headers required on the PUT; do not omit or alter them."
    )
    upload_url_expires_at: datetime = Field(
        description="Time after which a fresh upload URL must be requested."
    )
    session_expires_at: datetime = Field(
        description="Time after which the upload_id can no longer be ingested."
    )
    max_bytes: int = Field(
        default=MAX_PDF_BYTES, description="Maximum accepted PDF size in bytes."
    )
    next_step: str = Field(
        default="upload_pdf_then_call_ingest_paper_with_upload_id",
        description="Machine-readable continuation instruction.",
    )


@dataclass(frozen=True, slots=True)
class PaperUploadRecord:
    id: UUID
    actor_id: int
    project_id: UUID | None
    filename: str
    size_bytes: int
    sha256: str
    add_to_library: bool
    object_key: str
    status: str
    expires_at: datetime
    lease_expires_at: datetime | None
    lease_token: UUID | None


class PaperUploadGateway(Protocol):
    def create_or_refresh(
        self,
        *,
        actor: Actor,
        session_id: UUID,
        request: PreparePaperUploadRequest,
        object_key: str,
        expires_at: datetime,
        now: datetime,
    ) -> PaperUploadRecord: ...

    def claim(
        self,
        *,
        actor: Actor,
        upload_id: UUID,
        lease_token: UUID,
        lease_expires_at: datetime,
        now: datetime,
    ) -> PaperUploadRecord: ...

    def consume(
        self,
        *,
        actor: Actor,
        upload_id: UUID,
        lease_token: UUID,
        now: datetime,
    ) -> None: ...

    def release(
        self,
        *,
        actor: Actor,
        upload_id: UUID,
        lease_token: UUID,
        now: datetime,
        failed: bool,
    ) -> None: ...

    def delete_expired(self, *, now: datetime, limit: int) -> int: ...


class PaperUploadStore(Protocol):
    def sign_put(
        self,
        *,
        object_key: str,
        size_bytes: int,
        checksum_sha256_base64: str,
        expires_in_seconds: int,
    ) -> tuple[str, dict[str, str]]: ...


class PaperUploadSessions:
    def __init__(
        self,
        *,
        gateway: PaperUploadGateway,
        store: PaperUploadStore,
        clock: Clock,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._clock = clock

    def prepare(
        self,
        *,
        actor: Actor,
        request: PreparePaperUploadRequest,
    ) -> PreparePaperUploadResponse:
        if request.project_id is None and not request.add_to_library:
            raise AppError(
                code="add_to_library_false_requires_project",
                message="add_to_library=false requires a destination Project",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        now = self._clock.now()
        session_id = request.upload_id or uuid4()
        object_key = f"uploads/{actor.id}/{session_id}/source.pdf"
        record = self._gateway.create_or_refresh(
            actor=actor,
            session_id=session_id,
            request=request,
            object_key=object_key,
            expires_at=now + UPLOAD_SESSION_TTL,
            now=now,
        )
        self._gateway.delete_expired(now=now, limit=100)
        checksum = base64.b64encode(bytes.fromhex(record.sha256)).decode()
        try:
            url, headers = self._store.sign_put(
                object_key=record.object_key,
                size_bytes=record.size_bytes,
                checksum_sha256_base64=checksum,
                expires_in_seconds=UPLOAD_URL_TTL_SECONDS,
            )
        except RuntimeError as exc:
            raise AppError(
                code="paper_upload_url_unavailable",
                message="A secure PDF upload URL could not be created",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        return PreparePaperUploadResponse(
            upload_id=record.id,
            upload_url=url,
            headers=headers,
            upload_url_expires_at=now + timedelta(seconds=UPLOAD_URL_TTL_SECONDS),
            session_expires_at=record.expires_at,
        )

    def claim(self, *, actor: Actor, upload_id: UUID) -> PaperUploadRecord:
        now = self._clock.now()
        return self._gateway.claim(
            actor=actor,
            upload_id=upload_id,
            lease_token=uuid4(),
            lease_expires_at=now + UPLOAD_CLAIM_TTL,
            now=now,
        )

    def consume(self, *, actor: Actor, upload_id: UUID, lease_token: UUID) -> None:
        self._gateway.consume(
            actor=actor,
            upload_id=upload_id,
            lease_token=lease_token,
            now=self._clock.now(),
        )

    def release(
        self,
        *,
        actor: Actor,
        upload_id: UUID,
        lease_token: UUID,
        failed: bool,
    ) -> None:
        self._gateway.release(
            actor=actor,
            upload_id=upload_id,
            lease_token=lease_token,
            now=self._clock.now(),
            failed=failed,
        )


__all__ = [
    "PaperUploadRecord",
    "PaperUploadSessions",
    "PreparePaperUploadRequest",
    "PreparePaperUploadResponse",
    "UPLOAD_CLAIM_TTL",
    "UPLOAD_SESSION_TTL",
    "UPLOAD_URL_TTL_SECONDS",
]
