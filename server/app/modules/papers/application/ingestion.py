"""One PDF-ingestion use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.jobs.application.actions import JOB_CREATED, JOB_FAILED
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

PAPER_INGESTED = OperationAction("paper.ingested")


@dataclass(frozen=True, slots=True)
class FetchedPdf:
    content: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class AcceptedIngestion:
    ingestion: LibraryPaperIngestionResponse
    replayed: bool
    processing_required: bool


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
class PreparedPaperInput:
    content: bytes
    filename: str | None
    display_name: str
    source_kind: str


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

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> bool: ...

    def retry_source(self, *, actor: Actor, job_id: UUID) -> RetrySource: ...

    def cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        correlation_id: UUID,
        origin_operation_id: UUID,
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

    def cancel(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
    ) -> bool:
        changed = self._gateway.cancel(
            actor=actor,
            job_id=job_id,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef("job", str(job_id)),),
            )
        return changed
