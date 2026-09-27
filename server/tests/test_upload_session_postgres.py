"""Exercise the complete staged-upload workflow across real transaction boundaries."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import models as _models  # noqa: F401
from app.bootstrap.adapters.paper_ingestion import SqlPaperIngestionGateway
from app.bootstrap.container import build_paper_upload_sessions
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.jobs.infrastructure.models import DurableJob, JobDispatch
from app.modules.papers.application.ingestion import IngestPaper
from app.modules.papers.application.upload_sessions import (
    PreparePaperUploadRequest,
)
from app.modules.papers.infrastructure.upload_sessions import (
    PaperUploadSession,
    SqlPaperUploadGateway,
)
from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError
from app.shared.infrastructure.executor import SqlAlchemyApplicationExecutor


@pytest.fixture
def uploads():
    url = os.getenv("SCHOLENS_POSTGRES_TEST_URL")
    admin_url = os.getenv("SCHOLENS_POSTGRES_TEST_ADMIN_URL")
    if not url or not admin_url:
        pytest.skip("isolated PostgreSQL URLs are not configured")
    engine, admin = create_engine(url), create_engine(admin_url)
    email = f"upload-replay-{uuid4().hex}@example.com"
    with admin.begin() as db:
        actor_id = db.scalar(
            text(
                "INSERT INTO auth.users (email, password_hash, status) "
                "VALUES (:email, 'fixture', 'active') RETURNING id"
            ),
            {"email": email},
        )
        db.execute(
            text("INSERT INTO scholens.user_profiles (user_id) VALUES (:id)"),
            {"id": actor_id},
        )
    actor = Actor(id=actor_id, email=email, status="active", email_verified=True)
    journal = MagicMock()

    def capabilities(db):
        return SimpleNamespace(
            paper_ingestion=IngestPaper(
                validator=MagicMock(),
                limits=MagicMock(),
                journal=journal,
                gateway=SqlPaperIngestionGateway(db, staged_processing=True),
            ),
            paper_uploads=build_paper_upload_sessions(db=db),
        )

    executor = SqlAlchemyApplicationExecutor(sessionmaker(engine), capabilities)
    workflow = PaperIngestionWorkflow(
        executor=executor,
        url_source=MagicMock(),
        source_resolver=MagicMock(),
        operation_factory=OperationContextFactory(),
        jobs=MagicMock(),
    )
    upload_id = uuid4()
    with Session(engine) as db, db.begin():
        SqlPaperUploadGateway(db, require_project_upload=MagicMock()).create_or_refresh(
            actor=actor,
            session_id=upload_id,
            request=PreparePaperUploadRequest(
                filename="fixture.pdf", size_bytes=12, sha256="ab" * 32
            ),
            object_key=f"uploads/{actor_id}/{upload_id}/source.pdf",
            now=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

    def submit(**overrides):
        values = dict(
            actor=actor,
            upload_id=upload_id,
            project_id=None,
            idempotency_key="request-1",
            ip_address="127.0.0.1",
            operation=OperationContextFactory().root(
                initiated_by=OperationInitiator.USER,
                origin=CliOrigin("test-upload", uuid4()),
                credential=None,
            ),
        )
        return asyncio.run(workflow.from_upload_session(**(values | overrides)))

    metadata = SimpleNamespace(
        size_bytes=12,
        checksum_sha256=base64.b64encode(bytes.fromhex("ab" * 32)).decode(),
    )
    with patch(
        "app.bootstrap.workflows.paper_ingestion.s3_service.staging_object_metadata",
        return_value=metadata,
    ) as storage:
        yield SimpleNamespace(
            engine=engine,
            actor=actor,
            upload_id=upload_id,
            submit=submit,
            storage=storage,
            journal=journal,
        )
    with admin.begin() as db:
        db.execute(
            text("DELETE FROM scholens.jobs WHERE requested_by_id=:id"),
            {"id": actor_id},
        )
        db.execute(
            text("DELETE FROM scholens.user_profiles WHERE user_id=:id"),
            {"id": actor_id},
        )
        db.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": actor_id})
    engine.dispose()
    admin.dispose()


@pytest.mark.parametrize("implicit_key", [False, True])
def test_receipt_survives_materialization_consumption_and_session_cleanup(
    uploads, implicit_key
):
    arguments = {"idempotency_key": None} if implicit_key else {}
    first = uploads.submit(**arguments)
    assert uploads.submit(**arguments).id == first.id
    with Session(uploads.engine) as db, db.begin():
        session = db.get(PaperUploadSession, uploads.upload_id)
        assert session.status == "consumed" and session.lease_token is None
        job = db.get(DurableJob, first.id)
        # The materialization callback adds these mutable facts to the same job.
        job.payload = {
            **job.payload,
            "content_sha256": "ab" * 32,
            "input_size_bytes": 12,
        }
        job.status = "completed"
        db.execute(
            delete(PaperUploadSession).where(PaperUploadSession.id == uploads.upload_id)
        )
    assert uploads.submit(**arguments).id == first.id
    uploads.storage.assert_called_once()
    uploads.journal.append_many.assert_called_once()
    with Session(uploads.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DurableJob)
                .where(DurableJob.requested_by_id == uploads.actor.id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(JobDispatch)
                .where(JobDispatch.job_id == first.id)
            )
            == 1
        )


def test_replay_rejects_changed_request_and_cancelled_history(uploads):
    first = uploads.submit()
    for changes in ({"upload_id": uuid4()}, {"add_to_library": False}):
        with pytest.raises(AppError, match="idempotency_key_reused"):
            uploads.submit(**changes)
    with Session(uploads.engine) as db, db.begin():
        db.get(DurableJob, first.id).status = "cancelled"
    with pytest.raises(AppError, match="paper_ingestion_cancelled"):
        uploads.submit()
    uploads.storage.assert_called_once()


def test_another_account_cannot_replay_an_owned_upload(uploads):
    uploads.submit()
    outsider = Actor(
        id=-917231, email="outside@example.com", status="active", email_verified=True
    )
    with pytest.raises(AppError, match="paper_upload_not_found"):
        uploads.submit(actor=outsider)
    uploads.storage.assert_called_once()


def test_replay_of_a_previously_accepted_job_does_not_depend_on_session_state(uploads):
    first = uploads.submit()
    # N-1 accepted the job and consumed the staging session in separate commits.
    with Session(uploads.engine) as db, db.begin():
        db.get(PaperUploadSession, uploads.upload_id).status = "prepared"
    assert uploads.submit().id == first.id
    uploads.storage.assert_called_once()
    uploads.journal.append_many.assert_called_once()


def test_acceptance_failure_rolls_back_consumption_and_outbox(uploads):
    original = SqlPaperIngestionGateway.accept_source

    def fail_after_dispatch(gateway, **values):
        original(gateway, **values)
        raise RuntimeError("commit-boundary failure")

    with patch.object(
        SqlPaperIngestionGateway,
        "accept_source",
        fail_after_dispatch,
    ):
        with pytest.raises(AppError, match="paper_upload_unavailable"):
            uploads.submit()
    with Session(uploads.engine) as db:
        assert db.get(PaperUploadSession, uploads.upload_id).status == "prepared"
        assert (
            db.scalar(
                select(func.count())
                .select_from(DurableJob)
                .where(DurableJob.requested_by_id == uploads.actor.id)
            )
            == 0
        )
    assert uploads.submit().id is not None


def test_retry_racing_acceptance_commit_observes_the_original_receipt(uploads):
    consuming, commit, retry_started = Event(), Event(), Event()
    original = SqlPaperUploadGateway.consume

    def pause_acceptance(gateway, **values):
        original(gateway, **values)
        consuming.set()
        assert commit.wait(10)

    def retry():
        retry_started.set()
        return uploads.submit()

    with (
        patch.object(SqlPaperUploadGateway, "consume", pause_acceptance),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(uploads.submit)
        try:
            assert consuming.wait(10)
            repeated = pool.submit(retry)
            assert retry_started.wait(10)
        finally:
            commit.set()
        assert first.result(timeout=10).id == repeated.result(timeout=10).id
    uploads.storage.assert_called_once()
    uploads.journal.append_many.assert_called_once()


def test_lost_lease_cannot_accept_or_release_a_new_claim(uploads):
    replacement = uuid4()

    def replace_lease(*_):
        with Session(uploads.engine) as db, db.begin():
            db.get(PaperUploadSession, uploads.upload_id).lease_token = replacement
        return uploads.storage.return_value

    uploads.storage.side_effect = replace_lease
    with pytest.raises(AppError, match="paper_upload_lease_lost"):
        uploads.submit()
    with Session(uploads.engine) as db:
        session = db.get(PaperUploadSession, uploads.upload_id)
        assert session.status == "claimed" and session.lease_token == replacement
        assert (
            db.scalar(
                select(func.count())
                .select_from(DurableJob)
                .where(DurableJob.requested_by_id == uploads.actor.id)
            )
            == 0
        )
