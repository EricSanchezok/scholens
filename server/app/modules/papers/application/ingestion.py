"""One PDF-ingestion use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from typing import Protocol
from uuid import UUID

from app.modules.jobs.application.actions import JOB_CANCELLED, JOB_CREATED, JOB_FAILED
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.modules.papers.domain import normalize_idempotency_key
from app.shared.application import Actor, OperationContext
from pydantic import BaseModel, ConfigDict

PAPER_INGESTED = OperationAction("paper.ingested")
PAPER_INGESTION_DISMISSED = OperationAction("paper.ingestion_dismissed")


@dataclass(frozen=True, slots=True)
class FetchedPdf:
    content: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class PreparedPaperSource:
    value: str
    resolved_url: str | None


@dataclass(frozen=True, slots=True)
class AcceptedIngestion:
    ingestion: LibraryPaperIngestionResponse
    replayed: bool
    processing_required: bool


@dataclass(frozen=True, slots=True)
class SourceReadyResult:
    document_id: UUID | None
    canonical_object_key: str
    process_required: bool
    reused: bool


@dataclass(frozen=True, slots=True)
class IngestionFinalization:
    task_id: str
    job_id: UUID
    document_id: UUID
    project_id: UUID | None
    changed: bool
    job_completed: bool


@dataclass(frozen=True, slots=True)
class RetrySource:
    job_id: UUID
    content_sha256: str
    filename: str | None
    display_name: str
    source_kind: str
    project_id: UUID | None
    add_to_library: bool


@dataclass(frozen=True, slots=True)
class PendingPaperSource:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class PreparedPaperInput:
    content: bytes
    filename: str | None
    display_name: str
    source_kind: str


class IngestionCancellationState(BaseModel):
    """Complete stable impact facts for cancelling one PDF ingestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    status: Literal["pending", "running", "failed", "cancelled"]
    job_updated_at: datetime
    reservation_id: UUID | None
    reservation_updated_at: datetime | None
    dismissed_at: datetime | None
    document_id: UUID | None
    project_id: UUID | None
    library_reference_created: bool
    project_reference_created: bool
    library_membership_id: UUID | None
    project_membership_id: UUID | None
    document_gc_will_be_evaluated: bool


@dataclass(frozen=True, slots=True)
class IngestionCancellationPlan:
    state: IngestionCancellationState


class PdfInputValidator(Protocol):
    def validate(self, *, content: bytes, source: str) -> None: ...


class PdfUrlSource(Protocol):
    async def fetch(self, *, url: str) -> FetchedPdf: ...


class PaperIngestionLimits(Protocol):
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        ip_address: str,
    ) -> None: ...

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None: ...

    async def release(self, *, actor: Actor, job_id: UUID) -> None: ...


class PaperIngestionGateway(Protocol):
    def accept(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        project_id: UUID | None,
        add_to_library: bool,
        content: bytes,
        filename: str | None,
        display_name: str,
        source_kind: str,
        idempotency_key: str | None,
        job_id: UUID,
        retry_of: UUID | None,
    ) -> AcceptedIngestion: ...

    def accept_source(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        project_id: UUID | None,
        add_to_library: bool,
        filename: str | None,
        display_name: str,
        source_kind: str,
        fingerprint: str,
        source_value: str | None,
        resolved_url: str | None,
        upload_id: UUID | None,
        upload_object_key: str | None,
        canonical_object_key: str | None,
        expected_sha256: str | None,
        idempotency_key: str | None,
        job_id: UUID,
        retry_of: UUID | None,
    ) -> AcceptedIngestion: ...

    def source_for_resolution(
        self, *, actor: Actor, job_id: UUID
    ) -> PendingPaperSource: ...

    def source_ready(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        source_sha256: str,
        size_bytes: int,
        staging_object_key: str,
        filename: str | None,
        attempt: int,
    ) -> SourceReadyResult: ...

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> bool: ...

    def retry_source(self, *, actor: Actor, job_id: UUID) -> RetrySource: ...

    def plan_cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
    ) -> IngestionCancellationPlan: ...

    def cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        correlation_id: UUID,
        origin_operation_id: UUID,
        plan: IngestionCancellationPlan | None = None,
    ) -> bool: ...


class IngestPaper:
    def __init__(
        self,
        *,
        validator: PdfInputValidator,
        limits: PaperIngestionLimits,
        gateway: PaperIngestionGateway,
        journal: OperationJournal,
    ) -> None:
        self._validator = validator
        self._limits = limits
        self._gateway = gateway
        self._journal = journal

    async def prepare_bytes(
        self,
        *,
        actor: Actor,
        content: bytes,
        filename: str | None,
        ip_address: str,
    ) -> PreparedPaperInput:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        self._validator.validate(content=content, source=filename or "upload")
        display_name = (filename or "paper.pdf").strip() or "paper.pdf"
        return PreparedPaperInput(
            content=content,
            filename=filename,
            display_name=display_name,
            source_kind="upload",
        )

    async def enforce_rate(self, *, actor: Actor, ip_address: str) -> None:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)

    def prepare_persisted(
        self,
        *,
        content: bytes,
        filename: str | None,
        display_name: str,
        source_kind: str,
    ) -> PreparedPaperInput:
        """Revalidate a persisted source without charging a new HTTP rate limit."""

        self._validator.validate(content=content, source=filename or "persisted upload")
        return PreparedPaperInput(
            content=content,
            filename=filename,
            display_name=display_name,
            source_kind=source_kind,
        )

    async def prepare_url(
        self,
        *,
        actor: Actor,
        url: str,
        source: PdfUrlSource,
        ip_address: str,
        display_name: str,
        source_kind: str,
    ) -> PreparedPaperInput:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        fetched = await source.fetch(url=url)
        self._validator.validate(content=fetched.content, source=fetched.filename)
        return PreparedPaperInput(
            content=fetched.content,
            filename=fetched.filename,
            display_name=display_name,
            source_kind=source_kind,
        )

    def accept(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        add_to_library: bool,
        idempotency_key: str | None,
        job_id: UUID,
        retry_of: UUID | None = None,
    ) -> AcceptedIngestion:
        accepted = self._gateway.accept(
            actor=actor,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            project_id=project_id,
            add_to_library=add_to_library,
            content=prepared.content,
            filename=prepared.filename,
            display_name=prepared.display_name,
            source_kind=prepared.source_kind,
            idempotency_key=normalize_idempotency_key(idempotency_key),
            job_id=job_id,
            retry_of=retry_of,
        )
        if not accepted.replayed:
            self._journal.append_many(
                actor=actor,
                operation=operation,
                changes=(
                    OperationChange(
                        action=JOB_CREATED,
                        resources=(ResourceRef("job", str(job_id)),),
                    )
                    for job_id in (accepted.ingestion.id,)
                ),
            )
        return accepted

    def accept_source(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID | None,
        add_to_library: bool,
        filename: str | None,
        display_name: str,
        source_kind: str,
        fingerprint: str,
        source_value: str | None,
        resolved_url: str | None,
        upload_id: UUID | None,
        idempotency_key: str | None,
        job_id: UUID,
        upload_object_key: str | None = None,
        canonical_object_key: str | None = None,
        expected_sha256: str | None = None,
        retry_of: UUID | None = None,
    ) -> AcceptedIngestion:
        accepted = self._gateway.accept_source(
            actor=actor,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            project_id=project_id,
            add_to_library=add_to_library,
            filename=filename,
            display_name=display_name,
            source_kind=source_kind,
            fingerprint=fingerprint,
            source_value=source_value,
            resolved_url=resolved_url,
            upload_id=upload_id,
            upload_object_key=upload_object_key,
            canonical_object_key=canonical_object_key,
            expected_sha256=expected_sha256,
            idempotency_key=normalize_idempotency_key(idempotency_key),
            job_id=job_id,
            retry_of=retry_of,
        )
        if not accepted.replayed:
            self._journal.append_many(
                actor=actor,
                operation=operation,
                changes=(
                    OperationChange(
                        action=JOB_CREATED,
                        resources=(ResourceRef("job", str(accepted.ingestion.id)),),
                    ),
                ),
            )
        return accepted

    def source_for_resolution(
        self, *, actor: Actor, job_id: UUID
    ) -> PendingPaperSource:
        return self._gateway.source_for_resolution(actor=actor, job_id=job_id)

    def source_ready(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        source_sha256: str,
        size_bytes: int,
        staging_object_key: str,
        filename: str | None,
        attempt: int,
    ) -> SourceReadyResult:
        del operation
        result = self._gateway.source_ready(
            actor=actor,
            job_id=job_id,
            source_sha256=source_sha256,
            size_bytes=size_bytes,
            staging_object_key=staging_object_key,
            filename=filename,
            attempt=attempt,
        )
        return result

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.acquire(actor=actor, job_id=job_id)

    async def release(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.release(actor=actor, job_id=job_id)

    def fail(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        error_code: str,
    ) -> None:
        changed = self._gateway.fail(
            actor=actor,
            job_id=job_id,
            error_code=error_code,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef(type="job", id=str(job_id)),),
            )

    def retry_source(self, *, actor: Actor, job_id: UUID) -> RetrySource:
        return self._gateway.retry_source(actor=actor, job_id=job_id)

    def plan_cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
    ) -> IngestionCancellationPlan:
        return self._gateway.plan_cancel(actor=actor, job_id=job_id)

    def cancel(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        plan: IngestionCancellationPlan | None = None,
    ) -> bool:
        if plan is None:
            plan = self.plan_cancel(actor=actor, job_id=job_id)
        changed = self._gateway.cancel(
            actor=actor,
            job_id=job_id,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            plan=plan,
        )
        if changed:
            action = (
                PAPER_INGESTION_DISMISSED
                if plan.state.status == "failed"
                else JOB_CANCELLED
            )
            self._journal.append(
                actor=actor,
                operation=operation,
                action=action,
                resources=(ResourceRef("job", str(job_id)),),
            )
        return changed
