"""Real PostgreSQL recovery of an already-paid immutable enrichment result."""

from datetime import UTC, datetime
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from scholens_job_contracts import JobResultManifest
from app.database.models import Document, LibraryPaper, ResearchItem
from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobExecution,
    JobResultInbox,
    JobResultEffect,
)
from app.modules.operation_journal.infrastructure.models import (
    OperationJournalEntryModel,
)
from app.operator_cli.capabilities import OperatorCapabilities
from app.shared.domain import AppError
from app.operator_cli.common import cli_operation
from tests.test_ai_evidence_postgres import (
    evidence_database as evidence_database,
    metadata,
)


@pytest.fixture
def rejected_enrichment(evidence_database):
    engine, document_id, content, actors = evidence_database
    job_id = uuid4()
    payload = {
        "task_id": str(job_id),
        "content_digest": hashlib.sha256(content.encode()).hexdigest(),
        "metadata": metadata(content, ["efficient method improved results"]).model_dump(
            mode="json"
        ),
    }
    raw = json.dumps(payload).encode()
    sha = hashlib.sha256(raw).hexdigest()
    manifest = JobResultManifest(
        claim_generation=1,
        storage_key=f"jobs/results/{job_id}/1/{sha}.json",
        sha256=sha,
        byte_size=len(raw),
    )
    with Session(engine) as db, db.begin():
        db.add(
            DurableJob(
                id=job_id,
                operation="document_enrich",
                status="failed",
                requested_by_id=actors[0].id,
                document_id=document_id,
                error_code="job_result_application_failed",
                completed_at=datetime.now(UTC),
                correlation_id=uuid4(),
                origin_operation_id=uuid4(),
                idempotency_key=f"recovery:{job_id}",
                payload={"content_digest": payload["content_digest"]},
            )
        )
        db.flush()
        db.add(JobExecution(job_id=job_id, claim_generation=1, claim_token=uuid4()))
        db.add(
            JobResultInbox(
                job_id=job_id,
                claim_generation=1,
                manifest=manifest.model_dump(mode="json"),
                status="rejected",
                attempt_count=8,
                error_code="ValidationError",
                request_id=uuid4(),
                delivery_ref="b" * 64,
            )
        )
    yield (
        engine,
        job_id,
        document_id,
        actors[0].model_copy(update={"is_admin": True}),
        manifest,
        payload,
    )
    with Session(engine) as db, db.begin():
        db.execute(
            delete(DurableJob).where(
                (DurableJob.document_id == document_id) | (DurableJob.id == job_id)
            )
        )


def recover(db, fixture, *, manifest=None):
    _, job_id, _, admin, original, payload = fixture
    return OperatorCapabilities(db).document_result_recovery.apply(
        actor=admin,
        operation=cli_operation("maintenance.recover-document-result"),
        job_id=job_id,
        manifest=manifest or original,
        payload=payload,
        reason="page-map-fix",
    )


def test_recovery_dry_run_rolls_back_then_commits_once_with_audit(rejected_enrichment):
    engine, job_id, document_id, _, _, _ = rejected_enrichment
    with Session(engine) as db:
        assert recover(db, rejected_enrichment)["status"] == "completed"
        db.rollback()
    with Session(engine) as db:
        assert db.get(DurableJob, job_id).status == "failed"
        assert db.get(JobResultInbox, (job_id, 1)).attempt_count == 8
        assert (
            db.scalar(
                select(ResearchItem.id).where(
                    ResearchItem.target_document_id == document_id
                )
            )
            is None
        )
    with Session(engine) as db, db.begin():
        assert recover(db, rejected_enrichment)["status"] == "completed"
    with Session(engine) as db:
        job, inbox = db.get(DurableJob, job_id), db.get(JobResultInbox, (job_id, 1))
        assert job.status == "completed" and job.error_code is None
        assert inbox.status == "applied" and inbox.attempt_count == 9
        assert (
            inbox.error_code == "ValidationError"
        )  # Keep the original rejection evidence.
        assert db.get(JobExecution, job_id).claim_generation == 1
        assert (
            db.scalar(select(JobResultEffect).where(JobResultEffect.job_id == job_id))
            is not None
        )
        assert (
            db.scalar(
                select(OperationJournalEntryModel).where(
                    OperationJournalEntryModel.action == "job.result_recovered",
                    OperationJournalEntryModel.actor_id == job.requested_by_id,
                )
            )
            is not None
        )
    with Session(engine) as db, pytest.raises(ValueError, match="not_recoverable"):
        recover(db, rejected_enrichment)


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "access",
        "owner",
        "generation",
        "cancelled",
        "different_manifest",
        "newer_job",
        "effects",
        "not_admin",
    ],
)
def test_recovery_refuses_changed_authority_or_result(rejected_enrichment, change):
    engine, job_id, document_id, admin, manifest, payload = rejected_enrichment
    with Session(engine) as db, db.begin():
        if change == "source":
            db.get(Document, document_id).raw_content = "Changed source."
        elif change == "access":
            db.execute(
                delete(LibraryPaper).where(
                    LibraryPaper.document_id == document_id,
                    LibraryPaper.user_id == admin.id,
                )
            )
        elif change == "owner":
            db.get(DurableJob, job_id).requested_by_id = None
        elif change == "generation":
            db.get(JobExecution, job_id).claim_generation = 2
        elif change == "cancelled":
            db.get(DurableJob, job_id).status = "cancelled"
        elif change == "newer_job":
            db.add(
                DurableJob(
                    operation="document_enrich",
                    document_id=document_id,
                    requested_by_id=admin.id,
                    correlation_id=uuid4(),
                    origin_operation_id=uuid4(),
                    idempotency_key=uuid4().hex,
                    payload={},
                )
            )
        elif change == "effects":
            db.add(
                JobResultEffect(
                    job_id=job_id, claim_generation=1, ordinal=0, payload={}
                )
            )
    if change == "different_manifest":
        manifest = manifest.model_copy(update={"sha256": "c" * 64})
    if change == "not_admin":
        rejected_enrichment = (
            engine,
            job_id,
            document_id,
            admin.model_copy(update={"is_admin": False}),
            manifest,
            payload,
        )
    with (
        Session(engine) as db,
        pytest.raises(AppError if change == "not_admin" else ValueError),
    ):
        with db.begin():
            recover(db, rejected_enrichment, manifest=manifest)
    with Session(engine) as db:
        assert db.get(DurableJob, job_id).status == (
            "cancelled" if change == "cancelled" else "failed"
        )
        assert db.get(JobResultInbox, (job_id, 1)).status == "rejected"


def test_recovery_application_failure_preserves_original_failure(rejected_enrichment):
    engine, job_id, *_ = rejected_enrichment
    with patch(
        "app.bootstrap.adapters.document_result_recovery.DocumentEnrichmentCompletion.complete",
        side_effect=RuntimeError("injected"),
    ):
        with (
            Session(engine) as db,
            pytest.raises(RuntimeError, match="injected"),
            db.begin(),
        ):
            recover(db, rejected_enrichment)
    with Session(engine) as db:
        assert db.get(DurableJob, job_id).status == "failed"
        assert db.get(JobResultInbox, (job_id, 1)).attempt_count == 8


def test_concurrent_recovery_commits_only_once(rejected_enrichment):
    engine, *_ = rejected_enrichment

    def attempt():
        try:
            with Session(engine) as db, db.begin():
                recover(db, rejected_enrichment)
            return "completed"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["completed", "document_result_not_recoverable"]
