"""Short PostgreSQL transactions for execution fences and the result inbox."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session
from scholens_job_contracts import (
    EXECUTION_LEASE_SECONDS,
    JobExecutionClaim,
    JobResultManifest,
    JobResultReceipt,
)

from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobExecution,
    JobResultInbox,
)
from app.modules.jobs.application.results import ReservedJobResult
from app.modules.jobs.application.callbacks import JobPostCommitAction
from app.modules.jobs.infrastructure.result_effects import JobEffectRepository
from app.shared.domain import AppError, FailureKind

from app.modules.jobs.domain.execution import execution_exhausted

LEASE = timedelta(seconds=EXECUTION_LEASE_SECONDS)
TERMINAL = {"completed", "failed", "cancelled"}


class JobResultRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require_transport(self, *, job_id: UUID, generation: int | None) -> None:
        job = self.db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                kind=FailureKind.NOT_FOUND,
            )
        execution = self.db.get(JobExecution, job_id)
        if execution is None and generation is None:
            return
        if (
            execution is not None
            and generation == execution.claim_generation
            and job.status == "running"
            and job.lease_expires_at is not None
            and job.lease_expires_at > datetime.now(UTC)
        ):
            return
        raise AppError(
            code="job_execution_fence_rejected",
            message="Job execution is no longer current",
            kind=FailureKind.CONFLICT,
        )

    def _lock(self, job_id: UUID) -> tuple[DurableJob, JobExecution]:
        # Every writer takes the job before the execution/result row.
        job = self.db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        execution = self.db.scalar(
            select(JobExecution).where(JobExecution.job_id == job_id).with_for_update()
        )
        if job is None or execution is None:
            raise AppError(
                code="job_execution_not_found",
                message="Job execution not found",
                kind=FailureKind.NOT_FOUND,
            )
        return job, execution

    def claim(
        self, *, job_id: UUID, claim_token: UUID, now: datetime | None = None
    ) -> JobExecutionClaim:
        now = now or datetime.now(UTC)
        job, execution = self._lock(job_id)
        if job.status in TERMINAL or (
            job.status == "running" and job.lease_expires_at is None
        ):
            return JobExecutionClaim(claimed=False)
        if (
            job.status == "running"
            and job.lease_expires_at is not None
            and job.lease_expires_at > now
        ):
            return JobExecutionClaim(
                claimed=execution.claim_token == claim_token,
                claim_generation=execution.claim_generation
                if execution.claim_token == claim_token
                else None,
                retry_after_seconds=(
                    max(1, min(180, int((job.lease_expires_at - now).total_seconds())))
                    if execution.claim_token != claim_token
                    else None
                ),
                recover_only=(
                    execution.claim_generation > 1
                    and job.payload.get("execution_replay") == "checkpoint_only"
                ),
            )
        if execution_exhausted(
            attempts=job.attempt_count, started_at=job.started_at, now=now
        ):
            # The recovery supervisor owns transactional domain compensation.
            return JobExecutionClaim(claimed=False)
        execution.claim_generation += 1
        execution.claim_token = claim_token
        job.status = "running"
        job.started_at = job.started_at or now
        job.lease_expires_at = now + LEASE
        job.attempt_count += 1
        self.db.flush()
        return JobExecutionClaim(
            claimed=True,
            claim_generation=execution.claim_generation,
            recover_only=(
                execution.claim_generation > 1
                and job.payload.get("execution_replay") == "checkpoint_only"
            ),
        )

    def heartbeat(
        self,
        *,
        job_id: UUID,
        generation: int,
        progress_code: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(UTC)
        job, execution = self._lock(job_id)
        if (
            job.status != "running"
            or execution.claim_generation != generation
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            return False
        job.lease_expires_at = now + LEASE
        if progress_code is not None:
            job.progress_code = progress_code
        return True

    def accept(
        self,
        *,
        job_id: UUID,
        manifest: JobResultManifest,
        request_id: UUID,
        delivery_ref: str,
    ) -> JobResultReceipt:
        job, execution = self._lock(job_id)
        accepted = False
        if (
            manifest.storage_key != manifest.key_for(job_id)
            or execution.claim_generation != manifest.claim_generation
        ):
            return JobResultReceipt(
                accepted=False, claim_generation=manifest.claim_generation
            )
        existing = self.db.get(JobResultInbox, (job_id, manifest.claim_generation))
        if existing is not None:
            accepted = JobResultManifest.model_validate(existing.manifest) == manifest
        elif (
            job.status == "running"
            and job.lease_expires_at is not None
            and job.lease_expires_at > datetime.now(UTC)
        ):
            self.db.add(
                JobResultInbox(
                    job_id=job_id,
                    claim_generation=manifest.claim_generation,
                    manifest=manifest.model_dump(mode="json"),
                    request_id=request_id,
                    delivery_ref=delivery_ref,
                )
            )
            # Ownership transfers to the inbox atomically. Broker recovery must
            # not reset the job while the accepted result is being applied.
            job.lease_expires_at = None
            if manifest.failure_code is None:
                job.progress_code = "finalizing"
            accepted = True
        self.db.flush()
        return JobResultReceipt(
            accepted=accepted, claim_generation=manifest.claim_generation
        )

    def reserve_next(self, *, now: datetime | None = None) -> ReservedJobResult | None:
        now = now or datetime.now(UTC)
        row = self.db.scalar(
            select(JobResultInbox)
            .join(DurableJob, DurableJob.id == JobResultInbox.job_id)
            .join(JobExecution, JobExecution.job_id == JobResultInbox.job_id)
            .where(
                DurableJob.status == "running",
                JobExecution.claim_generation == JobResultInbox.claim_generation,
                JobResultInbox.available_at <= now,
                or_(
                    JobResultInbox.status == "pending",
                    and_(
                        JobResultInbox.status == "applying",
                        JobResultInbox.apply_lease_expires_at < now,
                    ),
                ),
            )
            .order_by(JobResultInbox.available_at, JobResultInbox.job_id)
            .limit(1)
            .with_for_update(skip_locked=True, of=JobResultInbox)
        )
        if row is None:
            return None
        row.status = "applying"
        row.apply_claim_id = uuid4()
        row.apply_lease_expires_at = now + LEASE
        row.attempt_count += 1
        self.db.flush()
        return ReservedJobResult(
            job_id=row.job_id,
            generation=row.claim_generation,
            claim_id=row.apply_claim_id,
            manifest=JobResultManifest.model_validate(row.manifest),
            request_id=row.request_id,
            delivery_ref=row.delivery_ref,
        )

    def lock_application(self, reservation: ReservedJobResult) -> bool:
        self.db.execute(text("SET LOCAL lock_timeout = '5s'"))
        self.db.execute(text("SET LOCAL statement_timeout = '30s'"))
        job, execution = self._lock(reservation.job_id)
        row = self.db.scalar(
            select(JobResultInbox)
            .where(
                JobResultInbox.job_id == reservation.job_id,
                JobResultInbox.claim_generation == reservation.generation,
            )
            .with_for_update()
        )
        return bool(
            job.status == "running"
            and execution.claim_generation == reservation.generation
            and row is not None
            and row.status == "applying"
            and row.apply_claim_id == reservation.claim_id
            and row.apply_lease_expires_at is not None
            and row.apply_lease_expires_at > datetime.now(UTC)
        )

    def applied(
        self,
        reservation: ReservedJobResult,
        *,
        actions: tuple[JobPostCommitAction, ...] = (),
    ) -> None:
        row = self.db.get(JobResultInbox, (reservation.job_id, reservation.generation))
        if row is None or row.apply_claim_id != reservation.claim_id:
            raise RuntimeError("result_application_fence_lost")
        row.status = "applied"
        row.apply_claim_id = None
        row.apply_lease_expires_at = None
        self.enqueue_effects(reservation, actions=actions)

    def enqueue_effects(
        self,
        reservation: ReservedJobResult,
        *,
        actions: tuple[JobPostCommitAction, ...],
    ) -> None:
        JobEffectRepository(self.db).enqueue(
            job_id=reservation.job_id,
            generation=reservation.generation,
            actions=actions,
        )

    def terminal(self, job_id: UUID) -> bool:
        job = self.db.get(DurableJob, job_id)
        return job is None or job.status in TERMINAL

    def retry(self, reservation: ReservedJobResult, *, error_code: str) -> bool:
        job, execution = self._lock(reservation.job_id)
        row = self.db.scalar(
            select(JobResultInbox)
            .where(
                JobResultInbox.job_id == reservation.job_id,
                JobResultInbox.claim_generation == reservation.generation,
            )
            .with_for_update()
        )
        if row is None or row.apply_claim_id != reservation.claim_id:
            return False
        terminal = (
            job.status in TERMINAL
            or execution.claim_generation != reservation.generation
        )
        exhausted = row.attempt_count >= 8
        row.status = "rejected" if terminal or exhausted else "pending"
        row.error_code = error_code[:80]
        row.apply_claim_id = None
        row.apply_lease_expires_at = None
        row.available_at = datetime.now(UTC) + timedelta(
            seconds=min(60, 2**row.attempt_count)
        )
        # The application invokes the operation's failure handler in this same
        # transaction, including domain compensation and journal changes.
        return exhausted and not terminal
