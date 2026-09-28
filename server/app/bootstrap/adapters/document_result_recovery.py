"""Atomic operator recovery of a rejected, already-paid enrichment artifact."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from scholens_job_contracts import JobResultManifest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.bootstrap.adapters.document_stage_callbacks import (
    DocumentEnrichmentCallback,
    DocumentEnrichmentCompletion,
)
from app.bootstrap.adapters.document_job_callback_support import (
    PDF_SOURCE_FAILURE_CODES,
)
from app.modules.identity.application.identity import Identity
from app.modules.identity.domain import (
    AccountAccessFacts,
    require_product_access,
)
from app.modules.jobs.application.results import ReservedJobResult
from app.modules.jobs.application.result_recovery import (
    RecoveredDocumentResult,
    ReclassifiedPdfFailure,
)
from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobExecution,
    JobResultInbox,
    JobResultEffect,
)
from app.modules.jobs.infrastructure.result_inbox import JobResultRepository
from app.modules.papers.infrastructure.models import Document
from app.shared.application import (
    OperationContextFactory,
    OperationInitiator,
    JobOrigin,
    CredentialKind,
    CredentialRef,
)


class SqlDocumentResultRecovery:
    """No worker dispatch, paid call, failure compensation reversal, or schema edit."""

    def __init__(self, db: Session, *, identity: Identity) -> None:
        self._db, self._identity = db, identity

    def _candidate(
        self, job_id: UUID
    ) -> tuple[DurableJob, JobResultInbox, JobResultManifest]:
        self._db.execute(text("SET LOCAL lock_timeout = '5s'"))
        self._db.execute(text("SET LOCAL statement_timeout = '30s'"))
        job = self._db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        execution = self._db.scalar(
            select(JobExecution).where(JobExecution.job_id == job_id).with_for_update()
        )
        if job is None or execution is None:
            raise ValueError("document_result_not_recoverable")
        inbox = self._db.scalar(
            select(JobResultInbox)
            .where(
                JobResultInbox.job_id == job_id,
                JobResultInbox.claim_generation == execution.claim_generation,
            )
            .with_for_update()
        )
        if (
            job.operation != "document_enrich"
            or job.status != "failed"
            or job.error_code != "job_result_application_failed"
            or job.requested_by_id is None
            or job.document_id is None
            or inbox is None
            or inbox.status != "rejected"
        ):
            raise ValueError("document_result_not_recoverable")
        manifest = JobResultManifest.model_validate(inbox.manifest)
        if (
            manifest.failure_code is not None
            or manifest.storage_key != manifest.key_for(job_id)
            or manifest.claim_generation != execution.claim_generation
            or manifest.byte_size > 512 * 1024
        ):
            raise ValueError("document_result_not_recoverable")
        # This narrow operation has no failure compensation. Refuse any unexpected
        # generation effects rather than reuse their ordinal or reverse them.
        if self._db.scalar(
            select(JobResultEffect.job_id)
            .where(
                JobResultEffect.job_id == job_id,
                JobResultEffect.claim_generation == execution.claim_generation,
            )
            .limit(1)
        ):
            raise ValueError("document_result_has_effects")
        return job, inbox, manifest

    def manifest(self, *, job_id: UUID) -> JobResultManifest:
        return self._candidate(job_id)[2]

    def reconcile_pdf_failure(self, *, job_id: UUID) -> ReclassifiedPdfFailure:
        """Correct only a proven historical misclassification, without replaying cleanup."""
        self._db.execute(text("SET LOCAL lock_timeout = '5s'"))
        self._db.execute(text("SET LOCAL statement_timeout = '30s'"))
        job = self._db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        execution = self._db.scalar(
            select(JobExecution).where(JobExecution.job_id == job_id).with_for_update()
        )
        if (
            job is None
            or execution is None
            or job.operation != "pdf_process"
            or job.status != "failed"
        ):
            raise ValueError("pdf_failure_not_reconcilable")
        inbox = self._db.scalar(
            select(JobResultInbox)
            .where(
                JobResultInbox.job_id == job_id,
                JobResultInbox.claim_generation == execution.claim_generation,
            )
            .with_for_update()
        )
        if inbox is None or inbox.status != "applied":
            raise ValueError("pdf_failure_not_reconcilable")
        manifest = JobResultManifest.model_validate(inbox.manifest)
        corrected = PDF_SOURCE_FAILURE_CODES.get(manifest.failure_code or "")
        if (
            corrected is None
            or manifest.claim_generation != execution.claim_generation
            or manifest.storage_key != manifest.key_for(job_id)
        ):
            raise ValueError("pdf_failure_not_reconcilable")
        previous = job.error_code
        if previous not in {corrected, "paper_ingestion_finalizing_failed"}:
            raise ValueError("pdf_failure_not_reconcilable")
        changed = previous != corrected
        if changed:
            job.error_code = corrected
        return ReclassifiedPdfFailure(
            changed=changed,
            previous_error=previous,
            error_code=corrected,
            result_sha256=manifest.sha256,
        )

    def apply(
        self,
        *,
        job_id: UUID,
        manifest: JobResultManifest,
        payload: dict[str, object],
    ) -> RecoveredDocumentResult:
        job, inbox, current_manifest = self._candidate(job_id)
        if current_manifest != manifest:
            raise ValueError("document_result_manifest_changed")
        assert job.requested_by_id is not None
        owner = self._identity.resolve_actor_by_user_id(job.requested_by_id)
        require_product_access(
            AccountAccessFacts(
                status=owner.status,
                is_admin=owner.is_admin,
                is_blocked=owner.is_blocked,
            )
        )
        callback = DocumentEnrichmentCallback.model_validate(payload)
        # Serialize with new stage creation and text repair before testing whether
        # another user-requested enrichment has superseded this failed result.
        self._db.execute(
            select(Document.id).where(Document.id == job.document_id).with_for_update()
        )
        if self._db.scalar(
            select(DurableJob.id)
            .where(
                DurableJob.document_id == job.document_id,
                DurableJob.requested_by_id == job.requested_by_id,
                DurableJob.operation == job.operation,
                DurableJob.id != job_id,
                DurableJob.created_at >= job.created_at,
            )
            .limit(1)
        ):
            raise ValueError("document_result_superseded")
        reservation = ReservedJobResult(
            job_id=job_id,
            generation=inbox.claim_generation,
            claim_id=uuid4(),
            manifest=manifest,
            request_id=inbox.request_id,
            delivery_ref=inbox.delivery_ref,
        )
        resumed = OperationContextFactory().resume(
            correlation_id=job.correlation_id,
            causation_id=job.origin_operation_id,
            initiated_by=OperationInitiator.SYSTEM,
            origin=JobOrigin(
                job_id=job_id,
                request_id=inbox.request_id,
                delivery_ref=inbox.delivery_ref,
            ),
            credential=CredentialRef(CredentialKind.INTERNAL_SIGNATURE),
        )
        # These transitions are never committed alone. Any validation, source or
        # access failure rolls back the original terminal failure and every write.
        job.status = "running"
        inbox.status = "applying"
        inbox.apply_claim_id = reservation.claim_id
        inbox.apply_lease_expires_at = datetime.now(UTC) + timedelta(seconds=180)
        inbox.attempt_count += 1
        result = DocumentEnrichmentCompletion(self._db).complete(
            actor=owner,
            operation=resumed,
            job_id=job_id,
            callback=callback,
        )
        if job.status != "completed":
            raise ValueError("document_result_source_or_access_changed")
        JobResultRepository(self._db).applied(reservation, actions=result.post_commit)
        return RecoveredDocumentResult(
            owner=owner,
            operation=resumed,
            changes=tuple(result.changes),
            generation=inbox.claim_generation,
            attempts=inbox.attempt_count,
            previous_error=inbox.error_code,
        )
