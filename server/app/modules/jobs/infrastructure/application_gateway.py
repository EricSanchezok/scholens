"""SQLAlchemy/outbox adapter for the public Jobs application ports."""

from __future__ import annotations

import builtins
from datetime import datetime
from uuid import UUID

from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.application.contracts import JobResponse
from app.modules.jobs.application.jobs import (
    EnqueueJobCommand,
    EnqueuedJob,
    OperationClaim,
    OperationTransition,
    ReserveOperationCommand,
    ReservedOperation,
)
from app.modules.jobs.infrastructure.repository import (
    CreateJob,
    EnqueueJob,
    job_repository,
)
from app.shared.domain.enums import JobOperation, JobStatus
from app.shared.domain import JsonValue
from sqlalchemy.orm import Session


def job_response(job: object) -> JobResponse:
    from app.modules.jobs.infrastructure.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse.model_validate(job, from_attributes=True)


def job_status_response(job: object) -> JobResponse:
    """Project a DurableJob without touching its deferred payload or result JSON."""

    from app.modules.jobs.infrastructure.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse(
        id=job.id,
        operation=job.operation,
        document_id=job.document_id,
        project_id=job.project_id,
        status=job.status,
        progress_code=job.progress_code,
        error_code=job.error_code,
        result=None,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


class SqlAlchemyJobsGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None:
        job = job_repository.find_by_idempotency_key(
            self._db,
            idempotency_key=key,
        )
        return job_response(job) if job is not None else None

    def enqueue(self, *, command: EnqueueJobCommand) -> EnqueuedJob:
        base_url = get_webhook_base_url().rstrip("/")
        task_kwargs: dict[str, JsonValue] = {"request": command.payload}
        if command.operation is not JobOperation.CONVERSATION_GENERATE:
            task_kwargs.update(
                {
                    "webhook_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}/complete"
                    ),
                    "claim_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}/claim"
                    ),
                }
            )
        if command.operation is JobOperation.DOCUMENT_REFLOW:
            task_kwargs["credential_url"] = (
                f"{base_url}/internal/v1/jobs/{command.job_id}"
                "/integration-credentials/mineru"
            )
        if command.operation in {JobOperation.ZOTERO_IMPORT, JobOperation.ZOTERO_SYNC}:
            task_kwargs.update(
                {
                    "credential_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}"
                        "/integration-credentials/zotero"
                    ),
                    "progress_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}/progress"
                    ),
                }
            )
        persisted = job_repository.enqueue(
            self._db,
            request=EnqueueJob(
                operation=command.operation,
                requested_by_id=command.requested_by_id,
                correlation_id=command.correlation_id,
                origin_operation_id=command.origin_operation_id,
                project_id=command.project_id,
                document_id=command.document_id,
                idempotency_key=command.idempotency_key,
                payload=command.payload,
                task_name=command.task_name,
                queue=command.queue,
                task_kwargs=task_kwargs,
                job_id=command.job_id,
            ),
        )
        return EnqueuedJob(
            job=job_response(persisted.job),
            created=persisted.created,
            payload=persisted.job.payload,
        )

    def reserve(self, *, command: ReserveOperationCommand) -> ReservedOperation:
        existing = job_repository.find_by_idempotency_key(
            self._db,
            idempotency_key=command.idempotency_key,
        )
        if existing is not None:
            return ReservedOperation(
                job=job_response(existing),
                payload=existing.payload,
                created=False,
            )
        persisted = job_repository.create(
            self._db,
            request=CreateJob(
                job_id=command.operation_id,
                operation=command.operation,
                requested_by_id=command.requested_by_id,
                correlation_id=command.correlation_id,
                origin_operation_id=command.origin_operation_id,
                idempotency_key=command.idempotency_key,
                payload=command.payload,
            ),
        )
        return ReservedOperation(
            job=job_response(persisted.job),
            payload=persisted.job.payload,
            created=persisted.created,
        )

    def complete(
        self,
        *,
        operation_id: UUID,
        claim_id: UUID,
        result: dict[str, JsonValue],
    ) -> OperationTransition:
        job, changed = job_repository.complete_claimed(
            self._db,
            job_id=operation_id,
            claim_id=claim_id,
            result=result,
        )
        return OperationTransition(job=job_response(job), changed=changed)

    def claim_completion(
        self,
        *,
        operation_id: UUID,
        requested_by_id: int,
    ) -> OperationClaim:
        job, claim_id, acquired = job_repository.claim_callback(
            self._db,
            job_id=operation_id,
            requested_by_id=requested_by_id,
        )
        return OperationClaim(
            job=job_response(job),
            claim_id=claim_id,
            acquired=acquired,
        )

    def heartbeat_completion(
        self,
        *,
        operation_id: UUID,
        requested_by_id: int,
        claim_id: UUID,
    ) -> bool:
        return job_repository.heartbeat_callback(
            self._db,
            job_id=operation_id,
            requested_by_id=requested_by_id,
            claim_id=claim_id,
        )

    def fail(
        self,
        *,
        operation_id: UUID,
        claim_id: UUID,
        error_code: str,
    ) -> OperationTransition:
        job, changed = job_repository.fail_claimed(
            self._db,
            job_id=operation_id,
            claim_id=claim_id,
            error_code=error_code,
        )
        return OperationTransition(job=job_response(job), changed=changed)

    def list(
        self,
        *,
        requested_by_id: int,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        statuses: tuple[JobStatus, ...] | None,
    ) -> builtins.list[JobResponse]:
        return [
            job_response(job)
            for job in job_repository.list_for_requester(
                self._db,
                requested_by_id=requested_by_id,
                project_id=project_id,
                document_id=document_id,
                operation=operation,
                statuses=statuses,
            )
        ]

    def list_statuses(
        self,
        *,
        requested_by_id: int,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        statuses: tuple[JobStatus, ...] | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> builtins.list[JobResponse]:
        return [
            job_status_response(job)
            for job in job_repository.list_statuses_for_requester(
                self._db,
                requested_by_id=requested_by_id,
                project_id=project_id,
                document_id=document_id,
                operation=operation,
                statuses=statuses,
                before_created_at=before_created_at,
                before_id=before_id,
                limit=limit,
            )
        ]

    def get(self, *, requested_by_id: int, job_id: UUID) -> JobResponse:
        return job_response(
            job_repository.require_for_requester(
                self._db,
                job_id=job_id,
                requested_by_id=requested_by_id,
            )
        )

    def get_many(
        self,
        *,
        requested_by_id: int,
        job_ids: tuple[UUID, ...],
    ) -> builtins.list[JobResponse]:
        return [
            job_response(job)
            for job in job_repository.require_many_for_requester(
                self._db,
                job_ids=job_ids,
                requested_by_id=requested_by_id,
            )
        ]

    def get_many_statuses(
        self,
        *,
        requested_by_id: int,
        job_ids: tuple[UUID, ...],
    ) -> builtins.list[JobResponse]:
        return [
            job_status_response(job)
            for job in job_repository.require_many_statuses_for_requester(
                self._db,
                job_ids=job_ids,
                requested_by_id=requested_by_id,
            )
        ]

    def payload(
        self,
        *,
        requested_by_id: int,
        job_id: UUID,
    ) -> dict[str, JsonValue]:
        return job_repository.require_for_requester(
            self._db,
            job_id=job_id,
            requested_by_id=requested_by_id,
        ).payload

    def cancel(self, *, requested_by_id: int, job_id: UUID) -> JobResponse:
        job, _changed = job_repository.cancel(
            self._db,
            job_id=job_id,
            requested_by_id=requested_by_id,
        )
        return job_response(job)
