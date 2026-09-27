"""Compensate abandoned fenced executions in the dispatcher's owning transaction."""

from sqlalchemy.orm import Session
from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.modules.jobs.infrastructure.models import DurableJob, JobExecution
from app.modules.jobs.infrastructure.result_effects import JobEffectRepository
from app.modules.identity.infrastructure.users import (
    actor_from_auth_user,
    user_repository,
)
from app.shared.application import (
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from uuid import uuid4


def recover_exhausted_fenced_job(
    db: Session, job: DurableJob, *, settings: AppSettings
) -> None:
    user = (
        user_repository.get(db, id=job.requested_by_id)
        if job.requested_by_id is not None
        else None
    )
    actor = (
        actor_from_auth_user(user)
        if user is not None and user.profile is not None
        else None
    )
    operation = OperationContextFactory().resume(
        correlation_id=job.correlation_id,
        causation_id=job.origin_operation_id,
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("exhausted_job_recovery", uuid4()),
        credential=None,
    )
    result = ApplicationCapabilities(db, settings).job_callbacks.fail_result(
        actor=actor,
        operation=operation,
        job_id=job.id,
        error_code="job_execution_retry_exhausted",
    )
    execution = db.get(JobExecution, job.id)
    if execution is None or job.status not in {"failed", "completed", "cancelled"}:
        raise RuntimeError("fenced_execution_compensation_incomplete")
    JobEffectRepository(db).enqueue(
        job_id=job.id, generation=execution.claim_generation, actions=result.post_commit
    )
