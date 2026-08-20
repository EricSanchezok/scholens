"""Public Jobs application facade and durable enqueue port."""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from scholens_job_contracts import JobQueue

from app.modules.jobs.application.contracts import (
    JobListResponse,
    JobResponse,
)
from app.shared.application import Actor
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, JobStatus


@dataclass(frozen=True, slots=True)
class EnqueueJobCommand:
    job_id: UUID
    operation: JobOperation
    requested_by_id: int
    correlation_id: UUID
    origin_operation_id: UUID
    idempotency_key: str
    payload: dict[str, JsonValue]
    task_name: str
    queue: JobQueue
    project_id: UUID | None = None
    document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReserveOperationCommand:
    operation_id: UUID
    operation: JobOperation
    requested_by_id: int
    correlation_id: UUID
    origin_operation_id: UUID
    idempotency_key: str
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ReservedOperation:
    job: JobResponse
    payload: dict[str, JsonValue]
    created: bool


@dataclass(frozen=True, slots=True)
class OperationTransition:
    job: JobResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class OperationClaim:
    job: JobResponse
    claim_id: UUID | None
    acquired: bool


@dataclass(frozen=True, slots=True)
class EnqueuedJob:
    job: JobResponse
    created: bool
    payload: dict[str, JsonValue] = field(default_factory=dict)


class JobCommandPort(Protocol):
    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None: ...

    def enqueue(self, *, command: EnqueueJobCommand) -> EnqueuedJob: ...


class IdempotentOperationPort(Protocol):
    def reserve(self, *, command: ReserveOperationCommand) -> ReservedOperation: ...

    def claim_completion(
        self,
        *,
        operation_id: UUID,
        requested_by_id: int,
    ) -> OperationClaim: ...

    def heartbeat_completion(
        self,
        *,
        operation_id: UUID,
        requested_by_id: int,
        claim_id: UUID,
    ) -> bool: ...

    def complete(
        self,
        *,
        operation_id: UUID,
        claim_id: UUID,
        result: dict[str, JsonValue],
    ) -> OperationTransition: ...

    def fail(
        self,
        *,
        operation_id: UUID,
        claim_id: UUID,
        error_code: str,
    ) -> OperationTransition: ...


class JobQueryPort(Protocol):
    def list(
        self,
        *,
        requested_by_id: int,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        statuses: tuple[JobStatus, ...] | None,
    ) -> builtins.list[JobResponse]: ...

    def get(self, *, requested_by_id: int, job_id: UUID) -> JobResponse: ...


class JobBatchQueryPort(JobQueryPort, Protocol):
    def get_many(
        self,
        *,
        requested_by_id: int,
        job_ids: tuple[UUID, ...],
    ) -> builtins.list[JobResponse]: ...


class Jobs:
    def __init__(self, queries: JobBatchQueryPort) -> None:
        self._queries = queries

    def list(
        self,
        *,
        actor: Actor,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        active: bool,
    ) -> JobListResponse:
        statuses = (JobStatus.PENDING, JobStatus.RUNNING) if active else None
        return JobListResponse(
            items=self._queries.list(
                requested_by_id=actor.id,
                project_id=project_id,
                document_id=document_id,
                operation=operation,
                statuses=statuses,
            )
        )

    def get(self, *, actor: Actor, job_id: UUID) -> JobResponse:
        return self._queries.get(requested_by_id=actor.id, job_id=job_id)

    def get_many(
        self,
        *,
        actor: Actor,
        job_ids: tuple[UUID, ...],
    ) -> builtins.list[JobResponse]:
        return self._queries.get_many(requested_by_id=actor.id, job_ids=job_ids)
