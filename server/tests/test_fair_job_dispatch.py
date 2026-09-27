"""Live PostgreSQL admission proofs: bounded broker backlog and requester fairness."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.database import models as _models  # noqa: F401
from app.modules.jobs.infrastructure.models import DurableJob, JobDispatch
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.shared.domain.enums import JobOperation


@pytest.fixture
def dispatch_database():
    url, admin_url = (
        os.getenv("SCHOLENS_POSTGRES_TEST_URL"),
        os.getenv("SCHOLENS_POSTGRES_TEST_ADMIN_URL"),
    )
    if not url or not admin_url:
        pytest.skip("isolated PostgreSQL URLs are not configured")
    engine, admin = create_engine(url), create_engine(admin_url)
    users = []
    with admin.begin() as conn:
        for _ in range(3):
            users.append(
                conn.scalar(
                    text(
                        "INSERT INTO auth.users (email, password_hash, status) VALUES (:email, 'fixture', 'active') RETURNING id"
                    ),
                    {"email": f"dispatch-{uuid4().hex}@example.com"},
                )
            )
    yield engine, users
    with Session(engine) as db, db.begin():
        db.execute(delete(DurableJob).where(DurableJob.requested_by_id.in_(users)))
    with admin.begin() as conn:
        conn.execute(
            text("DELETE FROM auth.users WHERE id = ANY(:ids)"), {"ids": users}
        )
    engine.dispose()
    admin.dispose()


def enqueue(engine, users, *, count=4, queue="document"):
    with Session(engine) as db, db.begin():
        return [
            job_repository.enqueue(
                db,
                request=EnqueueJob(
                    operation=JobOperation.PDF_PROCESS,
                    requested_by_id=owner,
                    correlation_id=uuid4(),
                    origin_operation_id=uuid4(),
                    idempotency_key=f"dispatch-test:{uuid4()}",
                    payload={},
                    task_name="upload_and_process_file",
                    queue=queue,
                ),
            ).job.id
            for owner in users
            for _ in range(count)
        ]


def reserve(engine):
    with Session(engine) as db, db.begin():
        return job_repository.reserve_dispatches(
            db, limit=20, lease=timedelta(seconds=30), fair=True
        )


def test_burst_is_bounded_and_new_requester_gets_the_next_turn(dispatch_database):
    engine, users = dispatch_database
    enqueue(engine, users[:2], count=20)
    first = reserve(engine)
    assert len(first) == 2
    assert {item.requested_by_id for item in first} == set(users[:2])
    assert reserve(engine) == ()
    enqueue(engine, users[2:])
    with Session(engine) as db, db.begin():
        db.get(DurableJob, first[0].job_id).status = "completed"
    next_turn = reserve(engine)
    assert len(next_turn) == 1 and next_turn[0].requested_by_id == users[2]


def test_parallel_dispatchers_cannot_overbook_or_duplicate(dispatch_database):
    engine, users = dispatch_database
    enqueue(engine, users)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reserve(engine), range(4)))
    admitted = [entry for result in results for entry in result]
    assert len(admitted) == 2
    assert len({entry.job_id for entry in admitted}) == 2
    assert len({entry.requested_by_id for entry in admitted}) == 2


def test_expired_publisher_recovers_without_extra_slot_and_cancellation_releases_it(
    dispatch_database,
):
    engine, users = dispatch_database
    enqueue(engine, users[:1])
    first = reserve(engine)
    assert len(first) == 1
    with Session(engine) as db, db.begin():
        dispatch = db.get(JobDispatch, first[0].dispatch_id)
        dispatch.available_at = datetime.now(UTC) - timedelta(seconds=1)
    replay = reserve(engine)
    assert [entry.job_id for entry in replay] == [first[0].job_id]
    assert replay[0].attempt_count == 2
    with Session(engine) as db, db.begin():
        db.get(DurableJob, replay[0].job_id).status = "cancelled"
    assert len(reserve(engine)) == 1


def test_queue_budgets_are_independent_and_rollback_keeps_pending_jobs(
    dispatch_database,
):
    engine, users = dispatch_database
    enqueue(engine, users[:1], queue="document")
    enqueue(engine, users[:1], queue="research")
    admitted = reserve(engine)
    assert {entry.queue for entry in admitted} == {"document", "research"}
    assert len(admitted) == 2
    with Session(engine) as db, db.begin():
        # N-1 publisher can continue using existing envelopes with the flag off.
        old = job_repository.reserve_dispatches(
            db, limit=20, lease=timedelta(seconds=30)
        )
        assert len(old) == 6
        assert all(entry.kwargs == {} for entry in old)
        assert (
            len(
                db.scalars(
                    select(DurableJob).where(DurableJob.requested_by_id == users[0])
                ).all()
            )
            == 8
        )


def test_backlog_snapshot_counts_unpublished_and_broker_pending_jobs(dispatch_database):
    from app.modules.jobs.infrastructure.backlog_observation import pending_backlog

    engine, users = dispatch_database
    ids = enqueue(engine, users[:1], count=5)
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        for index, job_id in enumerate(ids):
            job = db.get(DurableJob, job_id)
            job.created_at = now - timedelta(seconds=(index + 1) * 30)
        # Running and terminal work are not waiting; SQS status is not the
        # authority for the three remaining accepted jobs.
        db.get(DurableJob, ids[3]).status = "running"
        db.get(DurableJob, ids[4]).status = "cancelled"
        db.scalar(
            select(JobDispatch).where(JobDispatch.job_id == ids[1])
        ).status = "published"
        db.scalar(
            select(JobDispatch).where(JobDispatch.job_id == ids[2])
        ).status = "publishing"
    with Session(engine) as db:
        snapshot = {row.queue: row for row in pending_backlog(db, now=now)}
    assert len(snapshot) == 6
    assert snapshot["document"].pending_jobs == 3
    assert snapshot["document"].oldest_pending_seconds == 90
    assert snapshot["document-index"].pending_jobs == 0
    assert snapshot["document-index"].oldest_pending_seconds == 0


def test_backlog_age_does_not_become_negative(dispatch_database):
    from app.modules.jobs.infrastructure.backlog_observation import pending_backlog

    engine, users = dispatch_database
    ids = enqueue(engine, users[:1], count=1)
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.get(DurableJob, ids[0]).created_at = now + timedelta(seconds=10)
    with Session(engine) as db:
        snapshot = {row.queue: row for row in pending_backlog(db, now=now)}
    assert snapshot["document"].pending_jobs == 1
    assert snapshot["document"].oldest_pending_seconds == 0
