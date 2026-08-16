"""Cross-module infrastructure adapter for atomic paper ingestion."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NoReturn
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.bootstrap.adapters.document_submission import finalize_reserved_document
from app.bootstrap.adapters.upload_repository import upload_reservation_repository
from app.bootstrap.adapters.upload_reservations import reserve_upload
from app.database.models import (
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    ProjectPaper,
    UploadReservation,
)
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.helpers.parser import validate_pdf_content, validate_url_and_fetch_pdf
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.ingestion import (
    AcceptedIngestion,
    FetchedPdf,
    RetrySource,
)
from app.modules.papers.domain import content_sha256, normalize_doi
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.bootstrap.adapters.openalex import UserOpenAlex


class DefaultPdfInputValidator:
    def validate(self, *, content: bytes, source: str) -> None:
        valid, error = validate_pdf_content(content, source)
        if not valid:
            raise AppError(
                code="invalid_pdf",
                message=error or "The uploaded file is not a valid PDF",
                kind=FailureKind.INVALID_ARGUMENT,
            )


class SafePdfUrlSource:
    _ERRORS: tuple[tuple[tuple[str, ...], str, FailureKind], ...] = (
        (("too large",), "upload_too_large", FailureKind.INVALID_ARGUMENT),
        (("encrypted",), "pdf_encrypted", FailureKind.INVALID_ARGUMENT),
        (
            (
                "private",
                "non-public",
                "public addresses",
                "credentials",
                "scheme",
                "server address",
            ),
            "paper_source_unsafe_address",
            FailureKind.INVALID_ARGUMENT,
        ),
        (
            ("not a valid pdf", "corrupted", "unreadable", "too small"),
            "invalid_pdf",
            FailureKind.INVALID_ARGUMENT,
        ),
    )

    async def fetch(self, *, url: str) -> FetchedPdf:
        valid, content, error = await asyncio.to_thread(
            validate_url_and_fetch_pdf,
            url,
        )
        if not valid:
            normalized_error = (error or "").lower()
            for fragments, code, kind in self._ERRORS:
                if any(fragment in normalized_error for fragment in fragments):
                    raise AppError(
                        code=code,
                        message=error or "The PDF source could not be accepted",
                        kind=kind,
                    )
            raise AppError(
                code="paper_source_pdf_unavailable",
                message=error or "No safely accessible PDF is available",
                kind=FailureKind.UNAVAILABLE,
            )
        filename = (
            PurePosixPath(unquote(urlparse(url).path)).name or "downloaded-paper.pdf"
        )
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        return FetchedPdf(content=content, filename=filename)


class DefaultPaperSourceResolver:
    _ARXIV_ID = re.compile(
        r"^(?:[a-z-]+(?:\.[a-z-]+)?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$",
        re.IGNORECASE,
    )

    def __init__(self, *, openalex: UserOpenAlex) -> None:
        self._openalex = openalex

    async def resolve(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        kind: str,
        value: str,
    ) -> str:
        normalized = value.strip()
        if kind == "url":
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                self._raise_unavailable()
            return normalized
        if kind == "arxiv":
            arxiv_id = self.normalize_arxiv_id(normalized)
            if arxiv_id is None:
                self._raise_unavailable()
            return f"https://arxiv.org/pdf/{arxiv_id}"
        if kind == "doi":
            doi = normalize_doi(normalized)
            if doi is None:
                self._raise_unavailable()
            work = await self._openalex.find_by_doi(
                actor=actor,
                operation=operation,
                doi=doi,
            )
            if work is None:
                self._raise_unavailable()
            candidates = (
                work.primary_location.pdf_url if work.primary_location else None,
                work.open_access.oa_url if work.open_access else None,
            )
            for candidate in candidates:
                if candidate:
                    return candidate
            self._raise_unavailable()
        self._raise_unavailable()

    @classmethod
    def normalize_arxiv_id(cls, value: str) -> str | None:
        candidate = value.strip()
        if candidate.lower().startswith("arxiv:"):
            candidate = candidate[6:].strip()
        parsed = urlparse(candidate)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in {"http", "https"}:
                return None
            if parsed.hostname not in {"arxiv.org", "www.arxiv.org"}:
                return None
            candidate = parsed.path
        candidate = candidate.strip("/")
        for prefix in ("abs/", "pdf/"):
            if candidate.lower().startswith(prefix):
                candidate = candidate[len(prefix) :]
        if candidate.lower().endswith(".pdf"):
            candidate = candidate[:-4]
        return candidate if cls._ARXIV_ID.fullmatch(candidate) else None

    @staticmethod
    def _raise_unavailable() -> NoReturn:
        raise AppError(
            code="paper_source_pdf_unavailable",
            message="No safely accessible PDF is available for this source",
            kind=FailureKind.INVALID_ARGUMENT,
        )


class DefaultPaperIngestionLimits:
    async def enforce_rate(self, *, actor: Actor, ip_address: str) -> None:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=ip_address,
                feature="upload",
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="Upload rate limit exceeded",
            ) from None

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(job_id),
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="Too many background jobs are already running",
            ) from None

    async def release(self, *, actor: Actor, job_id: UUID) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="background",
            operation_id=str(job_id),
        )


class SqlPaperIngestionGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def response(
        reservation: UploadReservation,
        *,
        accepted_terminal: bool = False,
    ) -> LibraryPaperIngestionResponse:
        job = reservation.job
        stages = {
            "downloading",
            "parsing",
            "extracting_metadata",
            "indexing",
            "finalizing",
        }
        progress = job.progress_code
        if accepted_terminal:
            state, stage = "processing", "finalizing"
        elif job.status == JobStatus.RUNNING.value:
            state = "processing"
            stage = progress if progress in stages else "parsing"
        elif job.status == JobStatus.FAILED.value:
            state = "failed"
            stage = progress if progress in stages else "queued"
        else:
            state, stage = "queued", "queued"
        return LibraryPaperIngestionResponse.model_validate(
            {
                "id": job.id,
                "display_name": reservation.display_name,
                "source_kind": reservation.source_kind,
                "state": state,
                "stage": stage,
                "project_id": job.project_id,
                "document_id": job.document_id,
                "error_code": job.error_code,
                "created_at": job.created_at,
            }
        )

    def accept(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        project_id: UUID | None,
        content: bytes,
        filename: str | None,
        display_name: str,
        source_kind: str,
        idempotency_key: str | None,
        job_id: UUID,
        retry_of: UUID | None,
    ) -> AcceptedIngestion:
        original_reservation: UploadReservation | None = None
        durable_key: str | None = None
        if retry_of is not None:
            original = self._require_failed(actor=actor, job_id=retry_of, lock=True)
            original_reservation = self._db.get(UploadReservation, original.id)
            if original_reservation is None:
                self._not_found()
            durable_key = (
                f"pdf-ingestion-retry:{actor.id}:{retry_of}:{idempotency_key}"
                if idempotency_key is not None
                else None
            )

        reserved = reserve_upload(
            self._db,
            requester=actor,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            project_id=project_id,
            input_size_bytes=len(content),
            original_filename=filename,
            display_name=display_name,
            source_kind=source_kind,
            content_sha256=content_sha256(content),
            idempotency_key=idempotency_key,
            durable_idempotency_key=durable_key,
            job_id=job_id,
        )
        reservation = reserved.reservation
        accepted_terminal = reservation.job.status == JobStatus.COMPLETED.value
        if reserved.created:
            finalization = finalize_reserved_document(
                pdf_bytes=content,
                upload_job=reservation,
                user=actor,
                db=self._db,
            )
            accepted_terminal = finalization.job_completed
            if original_reservation is not None:
                original_reservation.superseded_by_id = reservation.id
        elif reservation.job.dispatch is None or reservation.job.document_id is None:
            # A returned ingestion must be complete enough for the outbox to publish.
            raise RuntimeError("accepted_ingestion_is_not_dispatchable")

        return AcceptedIngestion(
            ingestion=self.response(
                reservation,
                accepted_terminal=accepted_terminal,
            ),
            replayed=not reserved.created,
            processing_required=(
                reservation.job.status
                not in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}
            ),
        )

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> bool:
        reservation = upload_reservation_repository.get(
            self._db,
            id=job_id,
            user=actor,
        )
        if reservation is None:
            return False
        _job, changed = job_repository.fail(
            self._db,
            job_id=job_id,
            error_code=error_code,
        )
        return changed

    def retry_source(self, *, actor: Actor, job_id: UUID) -> RetrySource:
        original = self._require_failed(actor=actor, job_id=job_id, lock=False)
        reservation = self._db.get(UploadReservation, original.id)
        if reservation is None:
            self._not_found()
        return RetrySource(
            job_id=original.id,
            content_sha256=reservation.content_sha256,
            filename=reservation.original_filename,
            display_name=reservation.display_name,
            source_kind=reservation.source_kind,
            project_id=original.project_id,
        )

    def cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> bool:
        job = self._db.scalar(
            select(DurableJob)
            .where(
                DurableJob.id == job_id,
                DurableJob.requested_by_id == actor.id,
                DurableJob.operation == JobOperation.PDF_PROCESS.value,
            )
            .with_for_update()
        )
        if job is None:
            self._not_found()
        if job.status == JobStatus.CANCELLED.value:
            return False
        if job.status == JobStatus.COMPLETED.value:
            raise AppError(
                code="paper_ingestion_cancel_not_allowed",
                message="Completed paper ingestions cannot be cancelled",
                kind=FailureKind.CONFLICT,
            )
        reservation = self._db.get(UploadReservation, job.id)
        if reservation is None:
            self._not_found()
        if reservation.reference_created and job.document_id is not None:
            if job.project_id is None:
                self._db.execute(
                    delete(LibraryPaper).where(
                        LibraryPaper.user_id == actor.id,
                        LibraryPaper.document_id == job.document_id,
                    )
                )
            else:
                self._db.execute(
                    delete(ProjectPaper).where(
                        ProjectPaper.project_id == job.project_id,
                        ProjectPaper.document_id == job.document_id,
                    )
                )
            from app.bootstrap.adapters.document_gc import schedule_document_gc

            schedule_document_gc(
                self._db,
                document_id=job.document_id,
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
        job.status = JobStatus.CANCELLED.value
        job.completed_at = datetime.now(UTC)
        job.lease_expires_at = None
        job.progress_code = None
        self._db.flush()
        return True

    def _require_failed(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        lock: bool,
    ) -> DurableJob:
        statement = select(DurableJob).where(
            DurableJob.id == job_id,
            DurableJob.requested_by_id == actor.id,
            DurableJob.operation == JobOperation.PDF_PROCESS.value,
        )
        if lock:
            statement = statement.with_for_update()
        job = self._db.scalar(statement)
        if job is None:
            self._not_found()
        if job.status != JobStatus.FAILED.value:
            raise AppError(
                code="paper_ingestion_retry_not_allowed",
                message="Only failed paper ingestion jobs can be retried",
                kind=FailureKind.CONFLICT,
            )
        return job

    @staticmethod
    def _not_found() -> NoReturn:
        raise AppError(
            code="paper_ingestion_job_not_found",
            message="Paper ingestion job not found",
            kind=FailureKind.NOT_FOUND,
        )
