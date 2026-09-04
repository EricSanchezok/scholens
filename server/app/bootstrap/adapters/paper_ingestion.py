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
from app.helpers.s3 import document_source_key, source_staging_key, s3_service
from app.helpers.celery_config import get_webhook_base_url
from app.modules.billing.infrastructure.account_locks import lock_account_resource_quota
from app.modules.jobs.infrastructure.repository import (
    job_repository,
    requester_visible_job,
)
from app.modules.jobs.domain.lifecycle import can_cancel_job
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.ingestion import (
    AcceptedIngestion,
    FetchedPdf,
    IngestionCancellationPlan,
    IngestionCancellationState,
    RetrySource,
    SourceReadyResult,
)
from app.modules.papers.application.upload_intent import (
    resolve_add_to_library,
    resolve_created_memberships,
)
from app.modules.papers.domain import content_sha256, normalize_doi
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind, JsonValue
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
                work.best_oa_location.pdf_url if work.best_oa_location else None,
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
        add_to_library: bool,
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
            original_reservation = self._require_retry_reservation(original)
            add_to_library = resolve_add_to_library(
                original_reservation.add_to_library,
                project_id=original.project_id,
            )
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
            add_to_library=add_to_library,
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
        resolved_url: str | None,
        upload_id: UUID | None,
        idempotency_key: str | None,
        job_id: UUID,
        upload_object_key: str | None = None,
        expected_sha256: str | None = None,
    ) -> AcceptedIngestion:
        """Create a byte-free reservation and hand source materialization to Jobs."""
        fingerprint_matches = DurableJob.payload["source"]["fingerprint"].as_string()
        existing = self._db.scalar(
            select(UploadReservation)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                DurableJob.requested_by_id == actor.id,
                DurableJob.project_id == project_id,
                DurableJob.operation == JobOperation.PDF_PROCESS.value,
                fingerprint_matches == fingerprint,
                UploadReservation.dismissed_at.is_(None),
                DurableJob.status.in_(
                    (JobStatus.PENDING.value, JobStatus.RUNNING.value)
                ),
            )
            .limit(1)
        )
        if existing is not None:
            return AcceptedIngestion(
                ingestion=self.response(existing),
                replayed=True,
                processing_required=True,
            )
        source: dict[str, JsonValue] = {
            "kind": source_kind,
            "fingerprint": fingerprint,
            "resolved_url": resolved_url,
            "upload_id": str(upload_id) if upload_id is not None else None,
            "upload_object_key": upload_object_key,
            "expected_sha256": expected_sha256,
        }
        reserved = reserve_upload(
            self._db,
            requester=actor,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            project_id=project_id,
            input_size_bytes=0,
            original_filename=filename,
            display_name=display_name,
            source_kind=source_kind,
            content_sha256=None,
            add_to_library=add_to_library,
            idempotency_key=idempotency_key,
            job_id=job_id,
            source=source,
        )
        reservation = reserved.reservation
        durable_job = reservation.job
        if reserved.created:
            base_url = get_webhook_base_url().rstrip("/")
            staging_key = source_staging_key(str(durable_job.id))
            durable_job.payload = {
                **durable_job.payload,
                "source": source,
                "materialized": None,
                "staging_object_key": staging_key,
            }
            job_repository.add_dispatch(
                self._db,
                job=durable_job,
                task_name="ingest_source_and_process",
                queue="document",
                kwargs={
                    "source": source,
                    "staging_object_key": staging_key,
                    "source_ready_url": (
                        f"{base_url}/internal/v1/jobs/{durable_job.id}/source-ready"
                    ),
                    "webhook_url": (
                        f"{base_url}/internal/v1/jobs/{durable_job.id}/complete"
                    ),
                    "claim_url": f"{base_url}/internal/v1/jobs/{durable_job.id}/claim",
                    "progress_url": (
                        f"{base_url}/internal/v1/jobs/{durable_job.id}/progress"
                    ),
                    "credential_url": (
                        f"{base_url}/internal/v1/jobs/{durable_job.id}"
                        "/integration-credentials/mineru"
                    ),
                    "filename": filename,
                },
            )
            self._db.flush()
        elif durable_job.dispatch is None:
            raise RuntimeError("source_ingestion_is_not_dispatchable")
        return AcceptedIngestion(
            ingestion=self.response(reservation),
            replayed=not reserved.created,
            processing_required=durable_job.status
            not in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value},
        )

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
    ) -> SourceReadyResult:
        """Atomically promote a verified staging object to a canonical Document."""
        del attempt
        reservation = self._db.scalar(
            select(UploadReservation)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                UploadReservation.id == job_id,
                DurableJob.requested_by_id == actor.id,
                DurableJob.operation == JobOperation.PDF_PROCESS.value,
            )
            .with_for_update()
        )
        if reservation is None:
            self._not_found()
        job = reservation.job
        for owner_id in sorted(
            {
                reservation.quota_owner_id,
                *(
                    {reservation.library_quota_owner_id}
                    if reservation.library_quota_owner_id is not None
                    else set()
                ),
            }
        ):
            lock_account_resource_quota(self._db, user_id=owner_id)
        stored_digest = reservation.content_sha256
        if stored_digest is not None:
            if stored_digest != source_sha256:
                raise AppError(
                    code="source_checksum_mismatch",
                    message="The source digest does not match the reservation",
                    kind=FailureKind.CONFLICT,
                )
            stored_staging = job.payload.get("staging_object_key")
            if stored_staging != staging_object_key:
                raise AppError(
                    code="source_staging_key_mismatch",
                    message="The staged source does not belong to this job",
                    kind=FailureKind.CONFLICT,
                )
            if job.document_id is not None:
                document = job.document
                processing_required = bool(
                    job.status
                    not in {
                        JobStatus.COMPLETED.value,
                        JobStatus.FAILED.value,
                        JobStatus.CANCELLED.value,
                    }
                    and document is not None
                    and document.processing_job_id == job.id
                    and document.processing_status == "processing"
                )
                return SourceReadyResult(
                    document_id=job.document_id,
                    canonical_object_key=document_source_key(stored_digest),
                    process_required=processing_required,
                    reused=False,
                )
        if job.status in {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }:
            return SourceReadyResult(
                document_id=job.document_id,
                canonical_object_key=document_source_key(source_sha256),
                process_required=False,
                reused=True,
            )
        expected_staging = job.payload.get("staging_object_key")
        if expected_staging != staging_object_key:
            raise AppError(
                code="source_staging_key_mismatch",
                message="The staged source does not belong to this job",
                kind=FailureKind.CONFLICT,
            )
        source_payload = job.payload.get("source")
        expected_sha256 = (
            source_payload.get("expected_sha256")
            if isinstance(source_payload, dict)
            and isinstance(source_payload.get("expected_sha256"), str)
            else None
        )
        if expected_sha256 is not None and expected_sha256 != source_sha256:
            raise AppError(
                code="source_checksum_mismatch",
                message="The source digest does not match the prepared upload",
                kind=FailureKind.CONFLICT,
            )
        try:
            metadata = s3_service.staging_object_metadata(staging_object_key)
        except FileNotFoundError as exc:
            raise AppError(
                code="source_staging_missing",
                message="The staged source is no longer available",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        if metadata.size_bytes != size_bytes or size_bytes > 30 * 1024 * 1024:
            raise AppError(
                code="upload_too_large"
                if size_bytes > 30 * 1024 * 1024
                else "source_size_mismatch",
                message="The staged source size is invalid",
                kind=FailureKind.PAYLOAD_TOO_LARGE,
            )
        if metadata.checksum_sha256 is not None:
            import base64

            if (
                metadata.checksum_sha256
                != base64.b64encode(bytes.fromhex(source_sha256)).decode()
            ):
                raise AppError(
                    code="source_checksum_mismatch",
                    message="The staged source checksum is invalid",
                    kind=FailureKind.UNPROCESSABLE,
                )
        canonical_key = document_source_key(source_sha256)
        s3_service.copy_object(
            source_key=staging_object_key,
            destination_key=canonical_key,
        )
        job.payload = {
            **job.payload,
            "content_sha256": source_sha256,
            "input_size_bytes": size_bytes,
            "materialized": {
                "source_sha256": source_sha256,
                "size_bytes": size_bytes,
                "staging_object_key": staging_object_key,
            },
        }
        reservation.content_sha256 = source_sha256
        finalization = finalize_reserved_document(
            pdf_bytes=None,
            source_sha256=source_sha256,
            size_bytes=size_bytes,
            upload_job=reservation,
            user=actor,
            db=self._db,
            dispatch_processing=False,
        )
        self._db.flush()
        return SourceReadyResult(
            document_id=finalization.document_id,
            canonical_object_key=canonical_key,
            process_required=not finalization.job_completed,
            reused=finalization.task_id.startswith("reused:"),
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
        reservation = self._require_retry_reservation(original)
        digest = reservation.content_sha256
        if digest is None:
            raise AppError(
                code="paper_ingestion_retry_not_allowed",
                message="Source materialization must complete before retrying",
                kind=FailureKind.CONFLICT,
            )
        return RetrySource(
            job_id=original.id,
            content_sha256=digest,
            filename=reservation.original_filename,
            display_name=reservation.display_name,
            source_kind=reservation.source_kind,
            project_id=original.project_id,
            add_to_library=resolve_add_to_library(
                reservation.add_to_library,
                project_id=original.project_id,
            ),
        )

    def _plan_cancel_locked(
        self,
        *,
        actor: Actor,
        job_id: UUID,
    ) -> IngestionCancellationPlan:
        job = self._db.scalar(
            select(DurableJob)
            .where(
                DurableJob.id == job_id,
                DurableJob.requested_by_id == actor.id,
                DurableJob.operation == JobOperation.PDF_PROCESS.value,
                requester_visible_job(),
            )
            .with_for_update()
        )
        if job is None:
            self._not_found()
        if job.status == JobStatus.CANCELLED.value:
            return IngestionCancellationPlan(
                state=IngestionCancellationState(
                    job_id=job.id,
                    status="cancelled",
                    job_updated_at=job.updated_at,
                    reservation_id=None,
                    reservation_updated_at=None,
                    dismissed_at=None,
                    document_id=job.document_id,
                    project_id=job.project_id,
                    library_reference_created=False,
                    project_reference_created=False,
                    library_membership_id=None,
                    project_membership_id=None,
                    document_gc_will_be_evaluated=False,
                )
            )
        if job.status != JobStatus.FAILED.value and not can_cancel_job(
            JobStatus(job.status)
        ):
            raise AppError(
                code="paper_ingestion_cancel_not_allowed",
                message=(
                    "Only pending or running paper ingestions can be cancelled, "
                    "and only failed ingestions can be removed"
                ),
                kind=FailureKind.CONFLICT,
            )
        reservation = self._db.scalar(
            select(UploadReservation)
            .where(UploadReservation.id == job.id)
            .with_for_update()
        )
        if reservation is None:
            self._not_found()
        library_created, project_created = resolve_created_memberships(
            library_created=reservation.reference_created_library,
            project_created=reservation.reference_created_project,
            legacy_created=reservation.reference_created,
            project_id=job.project_id,
        )
        library_membership_id: UUID | None = None
        project_membership_id: UUID | None = None
        if job.document_id is not None and library_created:
            library_membership_id = self._db.scalar(
                select(LibraryPaper.id)
                .where(
                    LibraryPaper.user_id == actor.id,
                    LibraryPaper.document_id == job.document_id,
                )
                .with_for_update()
            )
        if (
            job.document_id is not None
            and job.project_id is not None
            and project_created
        ):
            project_membership_id = self._db.scalar(
                select(ProjectPaper.id)
                .where(
                    ProjectPaper.project_id == job.project_id,
                    ProjectPaper.document_id == job.document_id,
                )
                .with_for_update()
            )
        return IngestionCancellationPlan(
            state=IngestionCancellationState(
                job_id=job.id,
                status=(
                    "pending"
                    if job.status == JobStatus.PENDING.value
                    else (
                        "running" if job.status == JobStatus.RUNNING.value else "failed"
                    )
                ),
                job_updated_at=job.updated_at,
                reservation_id=reservation.id,
                reservation_updated_at=reservation.updated_at,
                dismissed_at=reservation.dismissed_at,
                document_id=job.document_id,
                project_id=job.project_id,
                library_reference_created=library_created,
                project_reference_created=project_created,
                library_membership_id=library_membership_id,
                project_membership_id=project_membership_id,
                document_gc_will_be_evaluated=(
                    job.document_id is not None and (library_created or project_created)
                ),
            )
        )

    def plan_cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
    ) -> IngestionCancellationPlan:
        return self._plan_cancel_locked(actor=actor, job_id=job_id)

    def cancel(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        correlation_id: UUID,
        origin_operation_id: UUID,
        plan: IngestionCancellationPlan | None = None,
    ) -> bool:
        if plan is None:
            plan = self._plan_cancel_locked(actor=actor, job_id=job_id)
        state = plan.state
        if state.job_id != job_id:
            raise RuntimeError("paper_ingestion_cancel_plan_mismatch")
        if state.status == JobStatus.CANCELLED.value or state.dismissed_at is not None:
            return False
        job = self._db.get(DurableJob, job_id)
        if job is None:
            self._not_found()
        if job.status != state.status:
            raise RuntimeError("paper_ingestion_cancel_plan_not_locked")
        if state.library_membership_id is not None:
            self._db.execute(
                delete(LibraryPaper).where(
                    LibraryPaper.id == state.library_membership_id
                )
            )
        if state.project_membership_id is not None:
            self._db.execute(
                delete(ProjectPaper).where(
                    ProjectPaper.id == state.project_membership_id
                )
            )
        if state.document_gc_will_be_evaluated:
            if state.document_id is None:
                raise RuntimeError("paper_ingestion_cancel_document_missing")
            from app.bootstrap.adapters.document_gc import schedule_document_gc

            schedule_document_gc(
                self._db,
                document_id=state.document_id,
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
        if state.status == JobStatus.FAILED.value:
            if state.reservation_id is None:
                raise RuntimeError("paper_ingestion_cancel_reservation_missing")
            reservation = self._db.get(UploadReservation, state.reservation_id)
            if reservation is None:
                self._not_found()
            reservation.dismissed_at = datetime.now(UTC)
        else:
            job.status = JobStatus.CANCELLED.value
            job.completed_at = datetime.now(UTC)
            job.lease_expires_at = None
            job.progress_code = None
        self._db.flush()
        return True

    def _require_retry_reservation(self, job: DurableJob) -> UploadReservation:
        reservation = self._db.get(UploadReservation, job.id)
        if reservation is None:
            self._not_found()
        if reservation.dismissed_at is not None:
            raise AppError(
                code="paper_ingestion_retry_not_allowed",
                message="Removed paper ingestions cannot be retried",
                kind=FailureKind.CONFLICT,
            )
        if (
            hasattr(reservation, "content_sha256")
            and reservation.content_sha256 is None
        ):
            raise AppError(
                code="paper_ingestion_retry_not_allowed",
                message="Source materialization must complete before retrying",
                kind=FailureKind.CONFLICT,
            )
        return reservation

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
            requester_visible_job(),
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
