"""Atomic operator recovery of a rejected, already-paid enrichment artifact."""

from datetime import UTC, datetime, timedelta
import re
from uuid import UUID, uuid4

from scholens_job_contracts import JobResultManifest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.bootstrap.adapters.document_stage_callbacks import (
    DocumentEnrichmentCallback,
    DocumentEnrichmentCompletion,
)
from app.modules.identity.application.identity import Identity
from app.modules.identity.domain import (
    AccountAccessFacts,
    require_administrator,
    require_product_access,
)
from app.modules.jobs.application.actions import JOB_COMPLETED
from app.modules.jobs.application.results import ReservedJobResult
from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobExecution,
    JobResultInbox,
    JobResultEffect,
)
from app.modules.jobs.infrastructure.result_inbox import JobResultRepository
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.infrastructure.models import Document
from app.shared.application import (
    Actor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    JobOrigin,
    CredentialKind,
    CredentialRef,
)


class DocumentResultRecovery:
    """No worker dispatch, paid call, failure compensation reversal, or schema edit."""

    def __init__(
        self, db: Session, *, identity: Identity, journal: OperationJournal
    ) -> None:
        self._db, self._identity, self._journal = db, identity, journal

    @staticmethod
    def _authorize(actor: Actor) -> None:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_admin=actor.is_admin,
                is_blocked=actor.is_blocked,
            )
        )

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

    def manifest(self, *, actor: Actor, job_id: UUID) -> JobResultManifest:
        self._authorize(actor)
        return self._candidate(job_id)[2]

    def apply(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        manifest: JobResultManifest,
        payload: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        self._authorize(actor)
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", reason) is None:
            raise ValueError("recovery_reason_must_be_a_bounded_identifier")
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
        self._journal.append_many(
            actor=owner, operation=resumed, changes=result.changes
        )
        self._journal.append(
            actor=owner,
            operation=resumed,
            action=JOB_COMPLETED,
            resources=(ResourceRef("job", str(job_id)),),
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=OperationAction("job.result_recovered"),
            resources=(
                ResourceRef("job", str(job_id)),
                ResourceRef("result_sha256", manifest.sha256),
                ResourceRef("generation", str(inbox.claim_generation)),
                ResourceRef("recovery_reason", reason),
            ),
        )
        return {
            "job_id": str(job_id),
            "status": job.status,
            "generation": inbox.claim_generation,
            "application_attempts": inbox.attempt_count,
            "previous_apply_error": inbox.error_code,
        }
