"""Observe accepted waiting work, including jobs not yet published to the broker."""

from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from scholens_job_contracts import JOB_QUEUE_NAMES
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.modules.jobs.infrastructure.models import DurableJob, JobDispatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingBacklog:
    queue: str
    pending_jobs: int
    oldest_pending_seconds: float


def pending_backlog(db: Session, *, now: datetime) -> tuple[PendingBacklog, ...]:
    rows = {
        queue: (count, oldest)
        for queue, count, oldest in db.execute(
            select(JobDispatch.queue, func.count(), func.min(DurableJob.created_at))
            .join(DurableJob, DurableJob.id == JobDispatch.job_id)
            .where(
                DurableJob.status == "pending", JobDispatch.queue.in_(JOB_QUEUE_NAMES)
            )
            .group_by(JobDispatch.queue)
        )
    }
    return tuple(
        PendingBacklog(
            queue=str(queue),
            pending_jobs=rows[queue][0] if queue in rows else 0,
            oldest_pending_seconds=(
                max(0.0, (now - rows[queue][1]).total_seconds())
                if queue in rows
                else 0.0
            ),
        )
        for queue in sorted(JOB_QUEUE_NAMES)
    )


def observe_pending_backlog() -> None:
    try:
        with SessionLocal() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
            snapshot = pending_backlog(db, now=datetime.now(UTC))
    except Exception as error:
        # A missing snapshot must not look like an empty queue. No SQL, user
        # identifiers, job payloads or exception text belongs in these logs.
        logger.error(
            "jobs.outbox.backlog_observation_failed",
            extra={"exception_type": type(error).__name__},
        )
        return
    for row in snapshot:
        logger.info(
            "jobs.outbox.backlog",
            extra={
                "queue": row.queue,
                "pending_jobs": row.pending_jobs,
                "oldest_pending_seconds": row.oldest_pending_seconds,
            },
        )
    logger.info("jobs.outbox.backlog_observed")
