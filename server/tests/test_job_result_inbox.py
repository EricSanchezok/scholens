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


def test_expired_owner_cannot_resurrect_lease_or_deliver_before_reclaim(database):
    engine, job_id = database
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        repo.claim(
            job_id=job_id,
            claim_token=uuid4(),
            now=datetime.now(UTC) - timedelta(seconds=181),
        )
        assert not repo.heartbeat(job_id=job_id, generation=1)
        assert not repo.accept(
            job_id=job_id,
            manifest=_manifest(job_id),
            request_id=uuid4(),
            delivery_ref="b" * 64,
        ).accepted


def test_transport_fence_rejects_unfenced_and_stale_source_mutations(database):
    from app.shared.domain import AppError

    engine, job_id = database
    with Session(engine) as db, db.begin():
        repo = JobResultRepository(db)
        repo.claim(job_id=job_id, claim_token=uuid4())
        repo.require_transport(job_id=job_id, generation=1)
        for generation in (None, 2):
            with pytest.raises(AppError, match="job_execution_fence_rejected"):
                repo.require_transport(job_id=job_id, generation=generation)
        db.get(DurableJob, job_id).status = "cancelled"
        with pytest.raises(AppError, match="job_execution_fence_rejected"):
            repo.require_transport(job_id=job_id, generation=1)


def test_paid_recovery_is_checkpoint_only_and_busy_owner_has_bounded_retry(database):
    engine, job_id = database
    now = datetime.now(UTC)
    token = uuid4()
    with Session(engine) as db, db.begin():
        db.get(DurableJob, job_id).payload = {"execution_replay": "checkpoint_only"}
        repo = JobResultRepository(db)
        first = repo.claim(job_id=job_id, claim_token=token, now=now)
        assert first.claimed and not first.recover_only
        busy = repo.claim(job_id=job_id, claim_token=uuid4(), now=now)
        assert not busy.claimed and busy.retry_after_seconds == 180
        second = repo.claim(
            job_id=job_id, claim_token=uuid4(), now=now + timedelta(seconds=181)
        )
        assert second.claimed and second.recover_only and second.claim_generation == 2


def test_nonterminal_handler_cannot_acknowledge_inbox(database):
    from unittest.mock import MagicMock
    from app.modules.jobs.application.results import JobResults
    from app.modules.jobs.infrastructure.models import JobResultInbox

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
    with pytest.raises(RuntimeError, match="not_applied"):
        with Session(engine) as db, db.begin():
            JobResults(JobResultRepository(db), MagicMock()).apply(
                reservation=reservation, actor=None, operation=MagicMock(), payload={}
            )
    with Session(engine) as db:
        assert db.get(JobResultInbox, (job_id, 1)).status == "applying"
        assert db.get(DurableJob, job_id).status == "running"


def test_exhaustion_runs_domain_compensation_and_inbox_rejection_atomically(database):
    from unittest.mock import MagicMock
    from app.modules.jobs.application.callbacks import JobCompletionResult
    from app.modules.jobs.application.results import JobResults
    from app.modules.jobs.infrastructure.models import JobResultInbox

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
        db.get(JobResultInbox, (job_id, 1)).attempt_count = 8
    with pytest.raises(RuntimeError, match="compensation interrupted"):
        with Session(engine) as db, db.begin():
            callbacks = MagicMock()
            callbacks.fail_result.side_effect = RuntimeError("compensation interrupted")
            JobResults(JobResultRepository(db), callbacks).retry(
                reservation=reservation,
                actor=None,
                operation=MagicMock(),
                error_code="InvalidArtifact",
            )
    with Session(engine) as db, db.begin():
        assert db.get(JobResultInbox, (job_id, 1)).status == "applying"
        callbacks = MagicMock()

        def compensate(**_kwargs):
            db.get(DurableJob, job_id).status = "failed"
            return JobCompletionResult(value={"accepted": True})

        callbacks.fail_result.side_effect = compensate
        JobResults(JobResultRepository(db), callbacks).retry(
            reservation=reservation,
            actor=None,
            operation=MagicMock(),
            error_code="InvalidArtifact",
        )
        assert db.get(JobResultInbox, (job_id, 1)).status == "rejected"
        assert db.get(DurableJob, job_id).status == "failed"
        callbacks.fail_result.assert_called_once()


def test_post_commit_effect_survives_restart_and_lost_acknowledgement(database):
    from unittest.mock import MagicMock
    from app.modules.jobs.application.callbacks import (
        JobCompletionResult,
        ReleaseJobConcurrency,
    )
    from app.modules.jobs.application.results import JobResults
    from app.modules.jobs.infrastructure.result_effects import JobEffectRepository

    engine, job_id = database
    action = ReleaseJobConcurrency(user_id=7, category="background", job_id=job_id)
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
    with Session(engine) as db, db.begin():
        callbacks = MagicMock()

        def complete(**_kwargs):
            db.get(DurableJob, job_id).status = "completed"
            return JobCompletionResult(value={"accepted": True}, post_commit=(action,))

        callbacks.complete.side_effect = complete
        result = JobResults(JobResultRepository(db), callbacks).apply(
            reservation=reservation, actor=None, operation=MagicMock(), payload={}
        )
        assert result.post_commit == ()
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        first = JobEffectRepository(db).reserve(now=now)
        assert first.action == action
    with Session(engine) as db, db.begin():
        repo = JobEffectRepository(db)
        assert repo.reserve(now=now + timedelta(seconds=10)) is None
        second = repo.reserve(now=now + timedelta(seconds=181))
        assert second.claim_id != first.claim_id
        assert not repo.finish(first)
        assert repo.finish(second)
    with Session(engine) as db, db.begin():
        assert JobEffectRepository(db).reserve(now=now + timedelta(seconds=400)) is None


def test_cleanup_waits_for_terminal_retention_and_pending_effects(database):
    from app.modules.jobs.application.callbacks import (
        DeleteJobResultArtifacts,
        ReleaseJobConcurrency,
    )
    from app.modules.jobs.infrastructure.result_effects import JobEffectRepository

    engine, job_id = database
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        repo = JobEffectRepository(db)
        repo.enqueue(
            job_id=job_id,
            generation=0,
            actions=(DeleteJobResultArtifacts(job_id),),
            available_at=now - timedelta(days=8),
        )
        assert repo.reserve(now=now) is None
        job = db.get(DurableJob, job_id)
        job.status, job.completed_at = "cancelled", now
        assert repo.reserve(now=now) is None
        job.completed_at = now - timedelta(days=8)
        repo.enqueue(
            job_id=job_id,
            generation=1,
            actions=(
                ReleaseJobConcurrency(user_id=7, category="background", job_id=job_id),
            ),
            available_at=now - timedelta(seconds=1),
        )
        effect = repo.reserve(now=now)
        assert isinstance(effect.action, ReleaseJobConcurrency)
        assert repo.reserve(now=now) is None
        repo.finish(effect)
        cleanup = repo.reserve(now=now)
        assert isinstance(cleanup.action, DeleteJobResultArtifacts)
        repo.finish(cleanup)
