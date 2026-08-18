"""PostgreSQL persistence for staged PDF upload sessions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from app.modules.papers.application.upload_sessions import (
    PaperUploadRecord,
    PreparePaperUploadRequest,
)
from app.modules.papers.application.upload_intent import resolve_add_to_library
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.infrastructure.persistence import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column


class PaperUploadSession(Base):
    __tablename__ = "paper_upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared','claimed','consumed','failed')",
            name="ck_paper_upload_sessions_status",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 31457280",
            name="ck_paper_upload_sessions_size",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_paper_upload_sessions_sha256",
        ),
        CheckConstraint(
            "(status = 'claimed') = "
            "(lease_expires_at IS NOT NULL AND lease_token IS NOT NULL)",
            name="ck_paper_upload_sessions_claim_lease",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    add_to_library: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared", server_default="prepared"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


Index(
    "ix_paper_upload_sessions_expiry",
    PaperUploadSession.expires_at,
    PaperUploadSession.status,
)


class SqlPaperUploadGateway:
    def __init__(
        self,
        db: Session,
        *,
        require_project_upload: Callable[[uuid.UUID, int], None],
    ) -> None:
        self._db = db
        self._require_project_upload = require_project_upload

    def create_or_refresh(
        self,
        *,
        actor: Actor,
        session_id: uuid.UUID,
        request: PreparePaperUploadRequest,
        object_key: str,
        expires_at: datetime,
        now: datetime,
    ) -> PaperUploadRecord:
        if request.project_id is not None:
            self._require_project_upload(request.project_id, actor.id)
        if request.upload_id is not None:
            model = self._owned(request.upload_id, actor.id, for_update=True)
            if model.status not in {"prepared", "claimed"}:
                raise AppError(
                    code="paper_upload_not_refreshable",
                    message="This upload session can no longer issue upload URLs",
                    kind=FailureKind.CONFLICT,
                )
            if (
                model.status == "claimed"
                and model.lease_expires_at is not None
                and model.lease_expires_at > now
            ):
                raise AppError(
                    code="paper_upload_in_use",
                    message="This upload session is currently being ingested",
                    kind=FailureKind.CONFLICT,
                )
            if (
                model.filename != request.filename
                or model.size_bytes != request.size_bytes
                or model.sha256 != request.sha256
                or model.project_id != request.project_id
                or resolve_add_to_library(
                    model.add_to_library,
                    project_id=model.project_id,
                )
                != request.add_to_library
            ):
                raise AppError(
                    code="paper_upload_metadata_mismatch",
                    message="The upload session metadata does not match this file",
                    kind=FailureKind.CONFLICT,
                )
            if model.expires_at <= now:
                raise AppError(
                    code="paper_upload_expired",
                    message="The upload session expired; prepare a new upload",
                    kind=FailureKind.CONFLICT,
                )
            model.status = "prepared"
            model.lease_expires_at = None
            model.lease_token = None
            model.updated_at = now
            return _record(model)
        model = PaperUploadSession(
            id=session_id,
            actor_id=actor.id,
            project_id=request.project_id,
            filename=request.filename,
            size_bytes=request.size_bytes,
            sha256=request.sha256,
            add_to_library=request.add_to_library,
            object_key=object_key,
            status="prepared",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self._db.add(model)
        self._db.flush()
        return _record(model)

    def claim(
        self,
        *,
        actor: Actor,
        upload_id: uuid.UUID,
        lease_token: uuid.UUID,
        lease_expires_at: datetime,
        now: datetime,
    ) -> PaperUploadRecord:
        model = self._owned(upload_id, actor.id, for_update=True)
        if model.expires_at <= now:
            raise AppError(
                code="paper_upload_expired",
                message="The upload session expired; prepare a new upload",
                kind=FailureKind.CONFLICT,
            )
        if model.status == "consumed":
            raise AppError(
                code="paper_upload_consumed",
                message="This upload session has already been ingested",
                kind=FailureKind.CONFLICT,
            )
        if model.status == "failed":
            raise AppError(
                code="paper_upload_failed",
                message="This upload session failed validation; prepare a new upload",
                kind=FailureKind.UNPROCESSABLE,
            )
        if (
            model.status == "claimed"
            and model.lease_expires_at is not None
            and model.lease_expires_at > now
        ):
            raise AppError(
                code="paper_upload_in_use",
                message="This upload session is already being ingested",
                kind=FailureKind.CONFLICT,
                retryable=True,
            )
        if model.project_id is not None:
            self._require_project_upload(model.project_id, actor.id)
        model.status = "claimed"
        model.lease_token = lease_token
        model.lease_expires_at = lease_expires_at
        model.updated_at = now
        self._db.flush()
        return _record(model)

    def consume(
        self,
        *,
        actor: Actor,
        upload_id: uuid.UUID,
        lease_token: uuid.UUID,
        now: datetime,
    ) -> None:
        model = self._owned(upload_id, actor.id, for_update=True)
        if (
            model.status != "claimed"
            or model.lease_token != lease_token
            or model.lease_expires_at is None
            or model.lease_expires_at <= now
        ):
            raise AppError(
                code="paper_upload_lease_lost",
                message="The upload session claim is no longer owned by this operation",
                kind=FailureKind.CONFLICT,
            )
        model.status = "consumed"
        model.consumed_at = now
        model.lease_expires_at = None
        model.lease_token = None
        model.updated_at = now
        self._db.flush()

    def release(
        self,
        *,
        actor: Actor,
        upload_id: uuid.UUID,
        lease_token: uuid.UUID,
        now: datetime,
        failed: bool,
    ) -> None:
        model = self._owned(upload_id, actor.id, for_update=True)
        if (
            model.status != "claimed"
            or model.lease_token != lease_token
            or model.lease_expires_at is None
            or model.lease_expires_at <= now
        ):
            return
        model.status = "failed" if failed else "prepared"
        model.lease_expires_at = None
        model.lease_token = None
        model.updated_at = now
        self._db.flush()

    def delete_expired(self, *, now: datetime, limit: int) -> int:
        expired_ids = tuple(
            self._db.scalars(
                select(PaperUploadSession.id)
                .where(PaperUploadSession.expires_at <= now)
                .order_by(PaperUploadSession.expires_at)
                .limit(limit)
            )
        )
        if not expired_ids:
            return 0
        self._db.execute(
            delete(PaperUploadSession)
            .where(PaperUploadSession.id.in_(expired_ids))
            .execution_options(synchronize_session=False)
        )
        return len(expired_ids)

    def _owned(
        self, upload_id: uuid.UUID, actor_id: int, *, for_update: bool
    ) -> PaperUploadSession:
        statement = select(PaperUploadSession).where(
            PaperUploadSession.id == upload_id,
            PaperUploadSession.actor_id == actor_id,
        )
        if for_update:
            statement = statement.with_for_update()
        model = self._db.scalar(statement)
        if model is None:
            raise AppError(
                code="paper_upload_not_found",
                message="Upload session not found",
                kind=FailureKind.NOT_FOUND,
            )
        return model


def _record(model: PaperUploadSession) -> PaperUploadRecord:
    return PaperUploadRecord(
        id=model.id,
        actor_id=model.actor_id,
        project_id=model.project_id,
        filename=model.filename,
        size_bytes=model.size_bytes,
        sha256=model.sha256,
        add_to_library=resolve_add_to_library(
            model.add_to_library,
            project_id=model.project_id,
        ),
        object_key=model.object_key,
        status=model.status,
        expires_at=model.expires_at,
        lease_expires_at=model.lease_expires_at,
        lease_token=model.lease_token,
    )


__all__ = ["PaperUploadSession", "SqlPaperUploadGateway"]
