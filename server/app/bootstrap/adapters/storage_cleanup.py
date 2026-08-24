"""Cross-module deletion of generated storage objects without a database owner."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from scholens_job_contracts import (
    JobQueue,
    chunk_storage_delete_keys,
    storage_delete_batch_digest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DurableJob, JobOperation
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.shared.domain import JsonValue

CREATED_CLEANUP_JOB_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ScheduledStorageDeletion:
    job_count: int
    created_job_count: int
    object_count: int


def schedule_storage_deletion(
    db: Session,
    *,
    object_keys: Iterable[str],
    idempotency_key: str,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> ScheduledStorageDeletion | None:
    base_url = get_webhook_base_url().rstrip("/")
    job_count = 0
    created_job_count = 0
    object_count = 0
    for batch_index, batch in enumerate(chunk_storage_delete_keys(object_keys)):
        digest = storage_delete_batch_digest(batch)
        durable_idempotency_key = (
            f"storage-delete:{idempotency_key}:batch:{batch_index:06d}:{digest}"
        )
        if len(durable_idempotency_key) > 255:
            raise ValueError("storage_delete_idempotency_key_too_large")
        keys_json: list[JsonValue] = list(batch)
        job_id = uuid.uuid4()
        persisted = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.STORAGE_DELETE,
                requested_by_id=None,
                correlation_id=correlation_id,
                origin_operation_id=origin_operation_id,
                idempotency_key=durable_idempotency_key,
                payload={
                    "object_keys": keys_json,
                    "object_count": len(batch),
                    "object_keys_digest": digest,
                    "batch_index": batch_index,
                },
                task_name="delete_storage_objects",
                queue=JobQueue.MAINTENANCE,
                task_kwargs={
                    "object_keys": keys_json,
                    "callback_url": (f"{base_url}/internal/v1/jobs/{job_id}/complete"),
                    "claim_url": f"{base_url}/internal/v1/jobs/{job_id}/claim",
                },
                job_id=job_id,
            ),
        )
        job_count += 1
        object_count += len(batch)
        if persisted.created:
            created_job_count += 1
    if job_count == 0:
        return None
    return ScheduledStorageDeletion(
        job_count=job_count,
        created_job_count=created_job_count,
        object_count=object_count,
    )


def iter_created_cleanup_job_ids(
    db: Session,
    *,
    origin_operation_id: uuid.UUID,
    operations: tuple[JobOperation, ...],
) -> Iterator[uuid.UUID]:
    """Re-read every cleanup Job created by one operation in bounded pages."""

    if not operations:
        return
    after_id: uuid.UUID | None = None
    operation_values = tuple(operation.value for operation in operations)
    while True:
        statement = (
            select(DurableJob.id)
            .where(
                DurableJob.origin_operation_id == origin_operation_id,
                DurableJob.operation.in_(operation_values),
            )
            .order_by(DurableJob.id)
            .limit(CREATED_CLEANUP_JOB_PAGE_SIZE)
        )
        if after_id is not None:
            statement = statement.where(DurableJob.id > after_id)
        page = tuple(db.scalars(statement).all())
        if not page:
            return
        yield from page
        after_id = page[-1]


__all__ = [
    "CREATED_CLEANUP_JOB_PAGE_SIZE",
    "ScheduledStorageDeletion",
    "iter_created_cleanup_job_ids",
    "schedule_storage_deletion",
]
