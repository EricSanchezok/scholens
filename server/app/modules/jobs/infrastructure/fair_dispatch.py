"""Bound broker backlog and rotate requesters before publishing durable work."""

from collections import defaultdict
from datetime import datetime

from scholens_job_contracts import JOB_QUEUE_NAMES
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobDispatch,
    JobDispatchCursor,
)

# A single worker needs one current delivery and one warm successor. The durable
# database holds the remaining backlog, where requester ordering is controllable.
QUEUE_IN_FLIGHT_LIMIT = 2


def select_fair_dispatches(
    db: Session, *, limit: int, now: datetime
) -> list[JobDispatch]:
    # Serialize only the short reservation transaction across API processes.
    # No waiting lock and no network publication while the lock is held.
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(1935896428, 2714)")):
        return []
    active: dict[str, list[int]] = defaultdict(list)
    owner = func.coalesce(DurableJob.requested_by_id, 0)
    for queue, requester in db.execute(
        select(JobDispatch.queue, owner)
        .join(DurableJob, DurableJob.id == JobDispatch.job_id)
        .where(
            DurableJob.status.in_(("pending", "running")),
            or_(
                JobDispatch.status == "published",
                and_(
                    JobDispatch.status == "publishing", JobDispatch.available_at > now
                ),
            ),
        )
    ):
        active[queue].append(requester)
    selected: list[JobDispatch] = []
    for queue in sorted(JOB_QUEUE_NAMES):
        slots = min(limit - len(selected), QUEUE_IN_FLIGHT_LIMIT - len(active[queue]))
        if slots <= 0:
            continue
        cursor = db.get(JobDispatchCursor, str(queue))
        if cursor is None:
            cursor = JobDispatchCursor(queue=str(queue), last_requester_id=0)
            db.add(cursor)
            db.flush()
        candidates = (
            select(JobDispatch.id, owner.label("requester"))
            .join(DurableJob, DurableJob.id == JobDispatch.job_id)
            .where(
                JobDispatch.queue == queue,
                JobDispatch.status.in_(("pending", "publishing")),
                JobDispatch.available_at <= now,
                DurableJob.status == "pending",
                owner.not_in(active[queue]),
            )
            .distinct(owner)
            .order_by(
                owner, JobDispatch.available_at, JobDispatch.created_at, JobDispatch.id
            )
            .subquery()
        )
        turns = (
            select(candidates.c.id, candidates.c.requester)
            .order_by(
                case((candidates.c.requester > cursor.last_requester_id, 0), else_=1),
                candidates.c.requester,
            )
            .limit(slots)
            .subquery()
        )
        dispatches = db.scalars(
            select(JobDispatch)
            .join(turns, turns.c.id == JobDispatch.id)
            .options(selectinload(JobDispatch.job))
            .order_by(
                case((turns.c.requester > cursor.last_requester_id, 0), else_=1),
                turns.c.requester,
            )
            .with_for_update(of=JobDispatch, skip_locked=True)
        ).all()
        for dispatch in dispatches:
            cursor.last_requester_id = dispatch.job.requested_by_id or 0
            selected.append(dispatch)
    return selected
