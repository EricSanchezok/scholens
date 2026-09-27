"""Real PostgreSQL proofs for fenced execution and durable result acceptance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.database import models as _models  # noqa: F401
from app.modules.jobs.infrastructure.models import DurableJob, JobExecution
from app.modules.jobs.infrastructure.result_inbox import JobResultRepository
from scholens_job_contracts import JobResultManifest


@pytest.fixture
def database():
    url = os.getenv("SCHOLENS_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("isolated PostgreSQL URL is not configured")
    engine = create_engine(url)
    job_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(
            DurableJob(
                id=job_id,
                operation="pdf_process",
                correlation_id=uuid4(),
                origin_operation_id=uuid4(),
                idempotency_key=f"inbox-test:{job_id}",
                payload={},
                status="pending",
            )
        )
        db.flush()
        db.add(JobExecution(job_id=job_id))
    yield engine, job_id
    with Session(engine) as db, db.begin():
        db.execute(delete(DurableJob).where(DurableJob.id == job_id))
    engine.dispose()


def _manifest(job_id, generation=1, digest="a" * 64):
    return JobResultManifest(
        claim_generation=generation,
        storage_key=f"jobs/results/{job_id}/{generation}/{digest}.json",
        sha256=digest,
        byte_size=128,
    )


def test_concurrent_claim_has_one_owner_and_lost_response_is_recoverable(database):
    engine, job_id = database
    tokens = [uuid4(), uuid4()]

    def claim(token):
        with Session(engine) as db, db.begin():
            return JobResultRepository(db).claim(job_id=job_id, claim_token=token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, tokens))
    assert sum(result.claimed for result in results) == 1
    winner = results.index(next(result for result in results if result.claimed))
    replay = claim(tokens[winner])
    assert replay.claimed and replay.claim_generation == 1


def test_expired_execution_cannot_heartbeat_or_submit_after_reclaim(database):
    engine, job_id = database
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        first = JobResultRepository(db).claim(
            job_id=job_id, claim_token=uuid4(), now=now
        )
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        second = repo.claim(
            job_id=job_id, claim_token=uuid4(), now=now + timedelta(seconds=181)
        )
        assert second.claim_generation == first.claim_generation + 1
        assert not repo.heartbeat(
            job_id=job_id, generation=1, now=now + timedelta(seconds=182)
        )
        assert not repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="b" * 64,
        ).accepted


def test_duplicate_result_is_stable_but_different_content_and_cancel_are_rejected(
    database,
):
    engine, job_id = database
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        repo.claim(job_id=job_id, claim_token=uuid4())
        receipt = repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="b" * 64,
        )
        assert receipt.accepted
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        assert repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="c" * 64,
        ).accepted
        assert not repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id, digest="d" * 64),
            request_id=uuid4(),
            delivery_ref="c" * 64,
        ).accepted
        assert not repo.claim(job_id=job_id, claim_token=uuid4()).claimed
        db.get(DurableJob, job_id).status = "cancelled"
    with Session(engine) as db, db.begin():
        assert JobResultRepository(db).reserve_next() is None


def test_inbox_recovers_after_restart_and_fences_the_previous_applier(database):
    engine, job_id = database
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        repo.claim(job_id=job_id, claim_token=uuid4())
        repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="b" * 64,
        )
        first = repo.reserve_next(now=now + timedelta(seconds=1))
        assert first is not None
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        assert repo.reserve_next(now=now + timedelta(seconds=1)) is None
        second = repo.reserve_next(now=now + timedelta(seconds=182))
        assert second is not None and second.claim_id != first.claim_id
        assert not repo.lock_application(first)
        assert repo.lock_application(second)
        repo.applied(second)
    with Session(engine) as db, db.begin():
        assert (
            JobResultRepository(db).reserve_next(now=now + timedelta(seconds=400))
            is None
        )


def test_business_effect_and_inbox_acknowledgement_rollback_together(database):
    from app.modules.jobs.application.callbacks import JobCompletionResult
    from app.modules.jobs.application.results import JobResults
    from app.modules.jobs.infrastructure.models import JobResultInbox
    from unittest.mock import MagicMock

    engine, job_id = database
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        repo.claim(job_id=job_id, claim_token=uuid4())
        repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="b" * 64,
        )
        reservation = repo.reserve_next(now=datetime.now(UTC) + timedelta(seconds=1))
        assert reservation is not None

    with pytest.raises(RuntimeError, match="connection lost"):
        with Session(engine) as db, db.begin():
            callbacks = MagicMock()

            def partial_completion(**_kwargs):
                db.get(DurableJob, job_id).status = "completed"
                db.flush()
                raise RuntimeError("connection lost")

            callbacks.complete.side_effect = partial_completion
            JobResults(JobResultRepository(db), callbacks).apply(
                reservation=reservation, actor=None, operation=MagicMock(), payload={}
            )

    with Session(engine) as db, db.begin():
        assert db.get(DurableJob, job_id).status == "running"
        assert db.get(JobResultInbox, (job_id, 1)).status == "applying"
        callbacks = MagicMock()

        def completed(**_kwargs):
            db.get(DurableJob, job_id).status = "completed"
            return JobCompletionResult(value={"accepted": True})

        callbacks.complete.side_effect = completed
        service = JobResults(JobResultRepository(db), callbacks)
        service.apply(
            reservation=reservation, actor=None, operation=MagicMock(), payload={}
        )
        service.apply(
            reservation=reservation, actor=None, operation=MagicMock(), payload={}
        )
        callbacks.complete.assert_called_once()
    with Session(engine) as db:
        assert db.get(DurableJob, job_id).status == "completed"
        assert db.get(JobResultInbox, (job_id, 1)).status == "applied"


def test_n_minus_one_job_can_claim_and_complete_on_expanded_schema(database):
    from app.modules.jobs.infrastructure.repository import job_repository

    engine, job_id = database
    with Session(engine) as db, db.begin():
        db.execute(delete(JobExecution).where(JobExecution.job_id == job_id))
        assert job_repository.claim(db, job_id=job_id) is not None
        job, changed = job_repository.complete(
            db, job_id=job_id, result={"legacy": True}
        )
        assert changed and job.status == "completed"
