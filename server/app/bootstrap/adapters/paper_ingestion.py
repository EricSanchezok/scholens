"""Cross-module infrastructure adapter for paper ingestion."""

from __future__ import annotations

import asyncio
import re
from pathlib import PurePosixPath
from typing import NoReturn
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from app.database.models import DurableJob, JobOperation, JobStatus, UploadReservation
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.helpers.paper_search import get_work_by_doi, normalize_doi
from app.helpers.parser import validate_pdf_content, validate_url_and_fetch_pdf
from app.modules.jobs.infrastructure.repository import CreateJob, job_repository
from app.modules.papers.application.ingestion import (
    FetchedPdf,
    IngestionFinalization,
    IngestionReservation,
    IngestionRetryReservation,
    ReapedStaleIngestion,
)
from app.modules.papers.domain import content_sha256, durable_ingestion_key
from app.bootstrap.adapters.document_submission import finalize_reserved_document
from app.bootstrap.adapters.upload_repository import (
    upload_reservation_repository,
)
from app.bootstrap.adapters.upload_reservations import reserve_upload
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy import select
from sqlalchemy.orm import Session


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
    async def fetch(self, *, url: str) -> FetchedPdf:
        valid, content, error = await asyncio.to_thread(
            validate_url_and_fetch_pdf,
            url,
        )
        if not valid:
            raise AppError(
                code="invalid_pdf_url",
                message=error or "The URL did not return a valid PDF",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        filename = (
            PurePosixPath(unquote(urlparse(url).path)).name or "downloaded-paper.pdf"
        )
        return FetchedPdf(content=content, filename=filename)


class DefaultPaperSourceResolver:
    _ARXIV_ID = re.compile(
        r"^(?:[a-z-]+(?:\.[a-z-]+)?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$",
        re.IGNORECASE,
    )

    async def resolve(self, *, kind: str, value: str) -> str:
        normalized = value.strip()
        if kind == "url":
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                self._raise_unavailable()
            return normalized
        if kind == "arxiv":
            arxiv_id = self._normalize_arxiv(normalized)
            if arxiv_id is None:
                self._raise_unavailable()
            return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        if kind == "doi":
            doi = normalize_doi(normalized)
            if doi is None:
                self._raise_unavailable()
            work = await asyncio.to_thread(get_work_by_doi, doi)
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
    def _normalize_arxiv(cls, value: str) -> str | None:
        parsed = urlparse(value)
        candidate = value
        if parsed.scheme or parsed.netloc:
            if parsed.hostname not in {"arxiv.org", "www.arxiv.org"}:
                return None
            candidate = parsed.path
        candidate = candidate.strip("/")
        for prefix in ("abs/", "pdf/"):
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
        if candidate.endswith(".pdf"):
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
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        ip_address: str,
    ) -> None:
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

    def reserve(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        project_id: UUID | None,
        content: bytes,
        filename: str | None,
        idempotency_key: str | None,
    ) -> IngestionReservation:
        durable_key = durable_ingestion_key(
            actor_id=actor.id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        replayed = (
            durable_key is not None
            and job_repository.find_by_idempotency_key(
                self._db,
                idempotency_key=durable_key,
            )
            is not None
        )
        reserved = reserve_upload(
            self._db,
            requester=actor,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            project_id=project_id,
            input_size_bytes=len(content),
            original_filename=filename,
            content_sha256=content_sha256(content),
            idempotency_key=idempotency_key,
        )
        reservation = reserved.reservation
        replayed = (
            replayed
            or reservation.job.dispatch is not None
            or reservation.job.document_id is not None
        )
        return IngestionReservation(
            job_id=reservation.id,
            replayed=replayed,
            reaped_stale_uploads=tuple(
                ReapedStaleIngestion(
                    job_id=reaped.job_id,
                    document_id=reaped.document_id,
                    project_id=reaped.project_id,
                    reference_removed=reaped.reference_removed,
                    document_processing_failed=reaped.document_processing_failed,
                    created_gc_job_id=reaped.created_gc_job_id,
                )
                for reaped in reserved.reaped_stale_uploads
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

    def finalize(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        content: bytes,
    ) -> IngestionFinalization:
        reservation = upload_reservation_repository.get(
            self._db,
            id=job_id,
            user=actor,
        )
        if reservation is None:
            raise RuntimeError("reserved_ingestion_not_found")
        return finalize_reserved_document(
            pdf_bytes=content,
            upload_job=reservation,
            user=actor,
            db=self._db,
        )

    def retry(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        correlation_id: UUID,
        origin_operation_id: UUID,
        idempotency_key: str | None,
    ) -> IngestionRetryReservation:
        original = self._db.scalar(
            select(DurableJob)
            .where(
                DurableJob.id == job_id,
                DurableJob.requested_by_id == actor.id,
            )
            .with_for_update()
        )
        if original is None:
            raise AppError(
                code="paper_ingestion_job_not_found",
                message="Paper ingestion job not found",
                kind=FailureKind.NOT_FOUND,
            )
        if (
            original.operation != JobOperation.PDF_PROCESS.value
            or original.status != JobStatus.FAILED.value
        ):
            raise AppError(
                code="paper_ingestion_retry_not_allowed",
                message="Only failed paper ingestion jobs can be retried",
                kind=FailureKind.CONFLICT,
            )
        original_reservation = self._db.get(UploadReservation, original.id)
        if original_reservation is None:
            raise AppError(
                code="paper_ingestion_job_not_found",
                message="Paper ingestion job not found",
                kind=FailureKind.NOT_FOUND,
            )
        durable_key = (
            f"pdf-ingestion-retry:{actor.id}:{job_id}:{idempotency_key}"
            if idempotency_key is not None
            else f"pdf-ingestion-retry:{actor.id}:{job_id}:{uuid4()}"
        )
        existing = job_repository.find_by_idempotency_key(
            self._db,
            idempotency_key=durable_key,
        )
        if existing is not None:
            if existing.payload.get("retry_of") != str(job_id):
                raise AppError(
                    code="idempotency_key_reused",
                    message="The idempotency key was already used for another request",
                    kind=FailureKind.CONFLICT,
                )
            return IngestionRetryReservation(
                job_id=existing.id,
                content_sha256=original_reservation.content_sha256,
                filename=original_reservation.original_filename,
                replayed=True,
            )
        new_job_id = uuid4()
        persisted = job_repository.create(
            self._db,
            request=CreateJob(
                operation=JobOperation.PDF_PROCESS,
                requested_by_id=actor.id,
                correlation_id=correlation_id,
                origin_operation_id=origin_operation_id,
                project_id=original.project_id,
                document_id=original.document_id,
                idempotency_key=durable_key,
                payload={
                    "content_sha256": original_reservation.content_sha256,
                    "original_filename": original_reservation.original_filename,
                    "input_size_bytes": original.payload.get("input_size_bytes", 0),
                    "retry_of": str(job_id),
                },
                job_id=new_job_id,
            ),
        )
        reservation = UploadReservation(
            id=persisted.job.id,
            quota_owner_id=original_reservation.quota_owner_id,
            reserved_size_kb=(
                original_reservation.reserved_size_kb
                if original.document_id is None
                else 0
            ),
            reserved_reference_count=(0 if original.document_id is not None else 1),
            content_sha256=original_reservation.content_sha256,
            original_filename=original_reservation.original_filename,
        )
        reservation.job = persisted.job
        self._db.add(reservation)
        self._db.flush()
        return IngestionRetryReservation(
            job_id=persisted.job.id,
            content_sha256=reservation.content_sha256,
            filename=reservation.original_filename,
            replayed=False,
        )
