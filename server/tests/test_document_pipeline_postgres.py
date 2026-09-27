"""Staged import facts and result application on real isolated PostgreSQL."""

import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session
from scholens_ai import evidence_segments

from app.database import models as _models  # noqa: F401
from app.bootstrap.adapters.document_stage_dispatch import enqueue_document_stages
from app.bootstrap.adapters.document_stage_callbacks import (
    DocumentEnrichmentCallback,
    DocumentEnrichmentCompletion,
)
from app.bootstrap.adapters.document_bibliography import (
    bibliography_snapshot,
    DocumentBibliographyCallback,
    DocumentBibliographyCompletion,
)
from app.modules.jobs.infrastructure.models import DurableJob, JobExecution
from app.modules.jobs.infrastructure.result_inbox import JobResultRepository
from app.modules.papers.infrastructure.models import Document, LibraryPaper
from app.modules.research.infrastructure.models import (
    ResearchItem,
    AiAnnotationEvidence,
)
from app.modules.papers.application.contracts.extraction import (
    PaperMetadataExtraction,
    AIHighlight,
)
from app.modules.papers.application.citations import CitationMetadataPatch
from app.shared.application import (
    Actor,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.shared.domain.enums import JobOperation


@pytest.fixture
def pipeline_database():
    url, admin_url = (
        os.getenv("SCHOLENS_POSTGRES_TEST_URL"),
        os.getenv("SCHOLENS_POSTGRES_TEST_ADMIN_URL"),
    )
    if not url or not admin_url:
        pytest.skip("isolated PostgreSQL URLs are not configured")
    engine, admin = create_engine(url), create_engine(admin_url)
    email = f"stages-{uuid4().hex}@example.com"
    with admin.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO auth.users (email, password_hash, status) VALUES (:email, 'fixture', 'active') RETURNING id"
            ),
            {"email": email},
        )
        connection.execute(
            text("INSERT INTO scholens.user_profiles (user_id) VALUES (:id)"),
            {"id": user_id},
        )
    actor = Actor(id=user_id, email=email, status="active", email_verified=True)
    doc_id, parent = uuid4(), uuid4()
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pipeline_test", uuid4()),
        credential=None,
    )
    source = "The measured latency is 12 milliseconds."
    with Session(engine) as db, db.begin():
        document = Document(
            id=doc_id,
            sha256=uuid4().hex * 2,
            original_filename="fixture.pdf",
            title="Human title",
            authors=["Zotero author"],
            size_bytes=1,
            s3_object_key=f"tests/{doc_id}.pdf",
            raw_content=source,
            parser_markdown_s3_key=f"tests/{doc_id}.md",
            processing_status="completed",
        )
        db.add(document)
        db.flush()
        db.add(LibraryPaper(user_id=user_id, document_id=doc_id))
        db.flush()
        stages = enqueue_document_stages(
            db,
            document=document,
            actor=actor,
            operation=operation,
            ingestion_job_id=parent,
            enrich=True,
        )
        ids = {stage.job.operation: stage.job.id for stage in stages}
    yield engine, doc_id, parent, actor, operation, source, ids
    with Session(engine) as db, db.begin():
        db.execute(delete(DurableJob).where(DurableJob.requested_by_id == user_id))
        db.execute(
            delete(ResearchItem).where(ResearchItem.target_document_id == doc_id)
        )
        db.execute(delete(LibraryPaper).where(LibraryPaper.document_id == doc_id))
        db.execute(delete(Document).where(Document.id == doc_id))
    with admin.begin() as connection:
        connection.execute(
            text("DELETE FROM scholens.user_profiles WHERE user_id=:id"),
            {"id": user_id},
        )
        connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user_id})
    engine.dispose()
    admin.dispose()


def test_fanout_is_idempotent_and_all_stages_have_independent_execution_fences(
    pipeline_database,
):
    engine, doc_id, parent, actor, operation, _source, ids = pipeline_database
    with Session(engine) as db, db.begin():
        result = enqueue_document_stages(
            db,
            document=db.get(Document, doc_id),
            actor=actor,
            operation=operation,
            ingestion_job_id=parent,
            enrich=True,
        )
        assert all(not stage.created for stage in result)
        assert {stage.job.id for stage in result} == set(ids.values())
        assert (
            len(
                db.scalars(
                    select(JobExecution).where(JobExecution.job_id.in_(ids.values()))
                ).all()
            )
            == 3
        )
        assert (
            db.get(DurableJob, ids["document_enrich"]).payload["execution_replay"]
            == "checkpoint_only"
        )
        assert (
            db.get(DurableJob, ids["document_index"]).payload["execution_replay"]
            == "deterministic"
        )


@pytest.mark.parametrize("stale", [False, True])
def test_optional_enrichment_fills_only_gaps_with_personal_generation_bound_evidence(
    pipeline_database, stale
):
    engine, doc_id, _parent, actor, operation, source, ids = pipeline_database
    job_id = ids[JobOperation.DOCUMENT_ENRICH.value]
    segment = next(evidence_segments(source))
    callback = DocumentEnrichmentCallback(
        task_id=job_id,
        content_digest=hashlib.sha256(source.encode()).hexdigest(),
        metadata=PaperMetadataExtraction(
            title="AI title",
            authors=["AI author"],
            summary="Summary",
            highlights=[
                AIHighlight(
                    text=source,
                    segment_id=segment.id,
                    annotation="Evidence",
                    type="result",
                )
            ],
        ),
    )
    with Session(engine) as db, db.begin():
        JobResultRepository(db).claim(job_id=job_id, claim_token=uuid4())
        if stale:
            db.execute(
                text(
                    "UPDATE scholens.documents SET raw_content='New source' WHERE id=:id"
                ),
                {"id": doc_id},
            )
        DocumentEnrichmentCompletion(db).complete(
            actor=actor, operation=operation, job_id=job_id, callback=callback
        )
    with Session(engine) as db:
        document, job = db.get(Document, doc_id), db.get(DurableJob, job_id)
        assert document.processing_status == "completed"
        assert document.title == "Human title" and document.authors == ["Zotero author"]
        assert job.status == ("failed" if stale else "completed")
        receipts = db.scalars(
            select(AiAnnotationEvidence).where(
                AiAnnotationEvidence.document_id == doc_id
            )
        ).all()
        assert len(receipts) == (0 if stale else 1)
        if not stale:
            assert (
                receipts[0].execution_generation == 1
                and receipts[0].user_id == actor.id
            )
            assert document.summary == "Summary"


def test_bibliography_result_cannot_cross_a_manual_identity_edit(pipeline_database):
    engine, doc_id, _parent, actor, operation, _source, ids = pipeline_database
    job_id = ids["document_bibliography"]
    with Session(engine) as db, db.begin():
        snapshot, fields = bibliography_snapshot(db, job_id=job_id, actor=actor)
        assert fields.title == "Human title"
        db.execute(
            text("UPDATE scholens.documents SET title='New human title' WHERE id=:id"),
            {"id": doc_id},
        )
        callback = DocumentBibliographyCallback(
            **snapshot.model_dump(exclude={"patch"}),
            task_id=job_id,
            patch=CitationMetadataPatch(doi="10.1000/test"),
        )
        DocumentBibliographyCompletion(db).complete(
            actor=actor, operation=operation, job_id=job_id, callback=callback
        )
    with Session(engine) as db:
        assert db.get(Document, doc_id).doi is None
        assert db.get(DurableJob, job_id).status == "failed"


@pytest.mark.parametrize("owner_available", [False, True])
def test_exhausted_pdf_compensation_commits_terminal_state_and_durable_release(
    pipeline_database, owner_available
):
    from datetime import UTC, datetime, timedelta
    from app.bootstrap.adapters.exhausted_job_recovery import (
        recover_exhausted_fenced_job,
    )
    from app.bootstrap.settings import AppSettings
    from app.modules.papers.infrastructure.models import UploadReservation
    from app.modules.identity.infrastructure.models import UserProfile
    from app.modules.jobs.infrastructure.models import JobResultEffect
    from app.modules.jobs.infrastructure.repository import job_repository

    engine, doc_id, _parent, actor, _operation, _source, ids = pipeline_database
    job_id = ids["document_index"]
    with Session(engine) as db, db.begin():
        job = db.get(DurableJob, job_id)
        job.operation = "pdf_process"
        JobResultRepository(db).claim(job_id=job_id, claim_token=uuid4())
        job.attempt_count = 4
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        document = db.get(Document, doc_id)
        document.processing_status, document.processing_job_id = "processing", job_id
        db.add(
            UploadReservation(
                id=job_id,
                quota_owner_id=actor.id,
                display_name="fixture.pdf",
                source_kind="file",
            )
        )
        if not owner_available:
            db.execute(delete(UserProfile).where(UserProfile.user_id == actor.id))
        db.flush()
        recovered = job_repository.recover_expired_leases(
            db,
            limit=10,
            recover_fenced=lambda session, source: recover_exhausted_fenced_job(
                session, source, settings=AppSettings(_env_file=None)
            ),
        )
        assert recovered == 1
    with Session(engine) as db:
        assert db.get(DurableJob, job_id).status == "failed"
        assert db.get(Document, doc_id).processing_status == "failed"
        effects = db.scalars(
            select(JobResultEffect).where(
                JobResultEffect.job_id == job_id, JobResultEffect.claim_generation == 1
            )
        ).all()
        assert any(
            effect.payload["kind"] == "release_concurrency" for effect in effects
        )
