"""Staged import facts and result application on real isolated PostgreSQL."""

import hashlib
import base64
import os
from uuid import uuid4
from uuid import UUID

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
            == 4
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


def test_stage_retry_is_owned_source_fenced_and_idempotent(pipeline_database):
    from app.bootstrap.adapters.document_processing import SqlDocumentProcessing
    from app.modules.papers.application.processing import RetryDocumentStage
    from app.shared.domain import AppError

    engine, doc_id, _parent, actor, operation, _source, ids = pipeline_database
    previous_id = ids[JobOperation.DOCUMENT_INDEX.value]
    with Session(engine) as db, db.begin():
        previous = db.get(DurableJob, previous_id)
        previous.status = "failed"
        gateway = SqlDocumentProcessing(db, enabled=True)
        before = gateway.get(actor=actor, document_id=doc_id)
        assert before.readable
        assert before.stages[0].can_retry
        request = RetryDocumentStage(job_id=previous_id, stage="index")
        first, created = gateway.retry(
            actor=actor, operation=operation, document_id=doc_id, request=request
        )
        second, repeated = gateway.retry(
            actor=actor, operation=operation, document_id=doc_id, request=request
        )
        assert created and not repeated
        assert first.job_id == second.job_id != previous_id
        new = db.get(DurableJob, first.job_id)
        assert str(new.id) in new.dispatch.kwargs["callback_url"]
        assert db.get(JobExecution, new.id) is not None
        assert db.get(Document, doc_id).processing_status == "completed"
        assert previous.status == "failed"
        other = Actor(
            id=actor.id + 1,
            email="other@example.com",
            status="active",
            email_verified=True,
        )
        with pytest.raises(AppError, match="paper_not_found"):
            gateway.get(actor=other, document_id=doc_id)


def test_stage_retry_rejects_changed_source_and_live_job(pipeline_database):
    from app.bootstrap.adapters.document_processing import SqlDocumentProcessing
    from app.modules.papers.application.processing import RetryDocumentStage
    from app.shared.domain import AppError

    engine, doc_id, _parent, actor, operation, _source, ids = pipeline_database
    previous_id = ids[JobOperation.DOCUMENT_INDEX.value]
    with Session(engine) as db, db.begin():
        gateway = SqlDocumentProcessing(db, enabled=True)
        request = RetryDocumentStage(job_id=previous_id, stage="index")
        with pytest.raises(AppError, match="document_stage_not_retryable"):
            gateway.retry(
                actor=actor, operation=operation, document_id=doc_id, request=request
            )
        db.get(DurableJob, previous_id).status = "failed"
        db.get(Document, doc_id).raw_content = "new source"
        db.flush()
        with pytest.raises(AppError, match="document_stage_not_retryable"):
            gateway.retry(
                actor=actor, operation=operation, document_id=doc_id, request=request
            )
        assert not gateway.get(actor=actor, document_id=doc_id).stages[0].can_retry


def test_ai_stage_retry_requires_explicit_paid_consent(pipeline_database):
    from app.bootstrap.adapters.document_processing import SqlDocumentProcessing
    from app.modules.papers.application.processing import (
        DocumentProcessing,
        RetryDocumentStage,
    )
    from app.shared.domain import AppError
    from unittest.mock import Mock

    engine, doc_id, _parent, actor, operation, _source, ids = pipeline_database
    with Session(engine) as db, db.begin():
        job_id = ids[JobOperation.DOCUMENT_ENRICH.value]
        db.get(DurableJob, job_id).status = "failed"
        journal = Mock()
        capability = DocumentProcessing(
            SqlDocumentProcessing(db, enabled=True), journal=journal, enabled=True
        )
        with pytest.raises(AppError, match="provider_charge_confirmation_required"):
            capability.retry(
                actor=actor,
                operation=operation,
                document_id=doc_id,
                request=RetryDocumentStage(stage="enrichment", job_id=job_id),
            )
        result = capability.retry(
            actor=actor,
            operation=operation,
            document_id=doc_id,
            request=RetryDocumentStage(
                stage="enrichment", job_id=job_id, acknowledge_provider_charge=True
            ),
        )
        assert result.job_id != job_id
        journal.append.assert_called_once()


def test_processing_status_hides_other_requesters_and_does_not_load_source(
    pipeline_database,
):
    from app.bootstrap.adapters.document_processing import SqlDocumentProcessing
    from sqlalchemy import inspect

    engine, doc_id, _parent, actor, _operation, _source, ids = pipeline_database
    with Session(engine) as db, db.begin():
        for job_id in ids.values():
            db.get(DurableJob, job_id).requested_by_id = None
        db.flush()
        document = SqlDocumentProcessing(db, enabled=True)._document(
            actor=actor, document_id=doc_id
        )
        assert "raw_content" in inspect(document).unloaded
        status = SqlDocumentProcessing(db, enabled=True).get(
            actor=actor, document_id=doc_id
        )
        assert all(
            stage.status == "not_requested" and stage.job_id is None
            for stage in status.stages
        )
        # Restore ownership for the fixture's cleanup.
        for job_id in ids.values():
            db.get(DurableJob, job_id).requested_by_id = actor.id


def test_concurrent_retry_has_one_execution(pipeline_database):
    from concurrent.futures import ThreadPoolExecutor
    from app.bootstrap.adapters.document_processing import SqlDocumentProcessing
    from app.modules.papers.application.processing import RetryDocumentStage

    engine, doc_id, _parent, actor, operation, _source, ids = pipeline_database
    job_id = ids[JobOperation.DOCUMENT_INDEX.value]
    with Session(engine) as db, db.begin():
        db.get(DurableJob, job_id).status = "failed"

    def submit():
        with Session(engine) as db, db.begin():
            return SqlDocumentProcessing(db, enabled=True).retry(
                actor=actor,
                operation=operation,
                document_id=doc_id,
                request=RetryDocumentStage(stage="index", job_id=job_id),
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = list(workers.map(lambda _: submit(), range(2)))
    assert first[0].job_id == second[0].job_id
    assert sum([first[1], second[1]]) == 1


def test_metadata_projection_is_durable_and_rejects_stale_metadata(pipeline_database):
    from app.bootstrap.adapters.document_search_projection import (
        enqueue_metadata_projection,
        DocumentSearchIndexCallback,
        DocumentSearchIndexCompletion,
    )
    from app.modules.papers.infrastructure.models import DocumentSearchEmbedding
    from scholens_ai import EMBEDDING_MODEL_REVISION

    engine, doc_id, _parent, actor, operation, _source, _ids = pipeline_database
    with Session(engine) as db, db.begin():
        document = db.get(Document, doc_id)
        pending = enqueue_metadata_projection(
            db, document=document, actor=actor, operation=operation
        )
        again = enqueue_metadata_projection(
            db, document=document, actor=actor, operation=operation
        )
        assert pending is not None and again is not None
        assert pending.job.id == again.job.id
        assert not again.created
        assert db.get(JobExecution, pending.job.id)
        callback = DocumentSearchIndexCallback(
            task_id=pending.job.id,
            source_digest=pending.job.payload["source_digest"],
            model_revision=EMBEDDING_MODEL_REVISION,
            embedding=[1.0] + [0.0] * 383,
        )
        accepted = DocumentSearchIndexCompletion(db).complete(
            actor=actor, operation=operation, job_id=pending.job.id, callback=callback
        )
        assert accepted.value["accepted"]
        db.flush()
        stored = db.get(DocumentSearchEmbedding, (doc_id, EMBEDDING_MODEL_REVISION))
        assert stored.source_digest == callback.source_digest
        document.title = "changed title"
        from datetime import datetime, timezone

        document.updated_at = datetime.now(timezone.utc)
        newer = enqueue_metadata_projection(
            db, document=document, actor=actor, operation=operation
        )
        assert newer is not None
        assert newer.job.id != pending.job.id
        document.title = "changed again before delivery"
        stale = DocumentSearchIndexCallback(
            task_id=newer.job.id,
            source_digest=newer.job.payload["source_digest"],
            model_revision=EMBEDDING_MODEL_REVISION,
            embedding=[0.0, 1.0] + [0.0] * 382,
        )
        rejected = DocumentSearchIndexCompletion(db).complete(
            actor=actor, operation=operation, job_id=newer.job.id, callback=stale
        )
        assert not rejected.value["accepted"]
        assert stored.source_digest == callback.source_digest


def test_metadata_repair_is_keyset_bounded_and_stale_safe(pipeline_database):
    from app.modules.papers.infrastructure.search_embedding_maintenance import (
        SqlSearchEmbeddingBackfill,
    )
    from app.modules.papers.application.maintenance import SearchEmbeddingWrite
    from scholens_ai import (
        EMBEDDING_MODEL_REVISION,
        semantic_document_text,
        semantic_source_digest,
    )

    engine, doc_id, _parent, _actor, _operation, _source, _ids = pipeline_database
    with Session(engine) as db, db.begin():
        gateway = SqlSearchEmbeddingBackfill(db)
        snapshot = gateway.candidates(batch_size=1)
        assert snapshot.scanned <= 1
        assert len(snapshot.items) <= 1
        if snapshot.next_cursor:
            next_page = gateway.candidates(
                batch_size=1, after_document_id=snapshot.next_cursor
            )
            assert all(
                item.document_id > snapshot.next_cursor for item in next_page.items
            )
        document = db.get(Document, doc_id)
        digest = semantic_source_digest(
            semantic_document_text(
                title=document.title,
                keywords=document.keywords,
                summary=document.summary,
                abstract=document.abstract,
            )
        )
        document.summary = "New canonical information"
        db.flush()
        assert gateway.apply_embeddings(
            records=(SearchEmbeddingWrite(doc_id, digest, (1.0,) + (0.0,) * 383),),
            model_revision=EMBEDDING_MODEL_REVISION,
        ) == (0, 1)


def test_n_minus_one_metadata_writers_invalidate_only_semantic_changes(
    pipeline_database,
):
    engine, doc_id, _parent, _actor, _operation, _source, _ids = pipeline_database
    with engine.begin() as db:
        before = db.scalar(
            text("SELECT search_revision FROM scholens.documents WHERE id=:id"),
            {"id": doc_id},
        )
        db.execute(
            text(
                "UPDATE scholens.documents SET processing_status='completed' WHERE id=:id"
            ),
            {"id": doc_id},
        )
        assert (
            db.scalar(
                text("SELECT search_revision FROM scholens.documents WHERE id=:id"),
                {"id": doc_id},
            )
            == before
        )
        # Existing applications know neither revision column.
        db.execute(
            text(
                "UPDATE scholens.documents SET title='Old application new title' WHERE id=:id"
            ),
            {"id": doc_id},
        )
        assert (
            db.scalar(
                text("SELECT search_revision FROM scholens.documents WHERE id=:id"),
                {"id": doc_id},
            )
            == before + 1
        )
        db.execute(
            text(
                "UPDATE scholens.documents SET title=title, summary=summary WHERE id=:id"
            ),
            {"id": doc_id},
        )
        assert (
            db.scalar(
                text("SELECT search_revision FROM scholens.documents WHERE id=:id"),
                {"id": doc_id},
            )
            == before + 1
        )


def test_sql_metadata_prefix_matches_canonical_unicode_and_long_whitespace(
    pipeline_database,
):
    from app.modules.papers.infrastructure.search_embedding_maintenance import (
        _metadata_columns,
    )
    from scholens_ai import semantic_document_text

    engine, doc_id, _parent, _actor, _operation, _source, _ids = pipeline_database
    with Session(engine) as db, db.begin():
        document = db.get(Document, doc_id)
        for title, keywords, summary, abstract in [
            (
                " " * 25000 + "标题",
                ["\u3000检索", "vector\u2000"],
                "\n摘要\t",
                "\u0085 abstract \u0085",
            ),
            (None, None, None, None),
            ("heading", ["检索" * 13000], "later", "excluded"),
        ]:
            document.title, document.keywords, document.summary, document.abstract = (
                title,
                keywords,
                summary,
                abstract,
            )
            db.flush()
            row = db.execute(
                select(*_metadata_columns()).where(Document.id == doc_id)
            ).one()
            assert row.semantic_text == semantic_document_text(
                title=title, keywords=keywords, summary=summary, abstract=abstract
            )
            assert len(row.semantic_text) <= 24000


def test_bounded_token_repair_adopts_once_and_rejects_changed_source(pipeline_database):
    from scholens_ai import (
        EMBEDDING_MODEL_REVISION,
        PassageEmbeddingRecord,
        TokenProjection,
        TokenSpan,
        encode_passage_embedding_artifact,
    )
    from app.modules.papers.infrastructure.token_index_maintenance import (
        SqlTokenIndexRepair,
    )

    engine, doc_id, _, _, _, source, _ = pipeline_database
    digest = hashlib.sha256(source.encode()).hexdigest()
    result = TokenProjection(
        content_digest=digest,
        model_revision=EMBEDDING_MODEL_REVISION,
        spans=[TokenSpan(start=0, end=len(source), tokens=10)],
        vectors=base64.b64encode(
            encode_passage_embedding_artifact(
                model_revision=EMBEDDING_MODEL_REVISION,
                records=[PassageEmbeddingRecord(digest, (1.0,) + (0.0,) * 383)],
            )
        ).decode(),
    )
    after = UUID(int=doc_id.int - 1)
    with Session(engine) as db, db.begin():
        repair = SqlTokenIndexRepair(db)
        page = repair.candidates(batch_size=1, after_document_id=after)
        assert page.scanned == 1 and page.document_ids == (doc_id,)
        assert repair.source(document_id=doc_id).raw_content == source
        with pytest.raises(ValueError):
            repair.candidates(batch_size=26, after_document_id=None)
        assert repair.apply_projection(document_id=doc_id, projection=result)
    with Session(engine) as db, db.begin():
        repair = SqlTokenIndexRepair(db)
        assert (
            repair.candidates(batch_size=1, after_document_id=after).document_ids == ()
        )
        db.get(Document, doc_id).raw_content = "changed canonical source"
        db.flush()
        assert not repair.apply_projection(document_id=doc_id, projection=result)
        assert repair.candidates(
            batch_size=1, after_document_id=after
        ).document_ids == (doc_id,)
        assert repair.source(document_id=uuid4()) is None
