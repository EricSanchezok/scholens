"""Real transaction proofs for partial, personal and replay-safe AI evidence."""

from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import pytest
from scholens_ai import evidence_segments
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import Session

from app.bootstrap.adapters.research_annotations import create_ai_annotations
from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.database.models import (
    Document,
    LibraryPaper,
    ResearchAudienceType,
    ResearchItem,
    RoleType,
)
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.research.application.positions import ParsedTextPosition
from app.modules.research.infrastructure.models import (
    AiAnnotationEvidence,
    AnnotationThread,
)
from app.shared.application import Actor


@pytest.fixture
def evidence_database():
    url = os.getenv("SCHOLENS_POSTGRES_TEST_URL")
    admin_url = os.getenv("SCHOLENS_POSTGRES_TEST_ADMIN_URL")
    if not url or not admin_url:
        pytest.skip("isolated PostgreSQL URLs are not configured")
    engine, admin = create_engine(url), create_engine(admin_url)
    actors = []
    with admin.begin() as connection:
        for _ in range(2):
            email = f"evidence-{uuid4().hex}@example.com"
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
            actors.append(
                Actor(id=user_id, email=email, status="active", email_verified=True)
            )
    document_id = uuid4()
    content = "The efﬁcient method improved results.\nThe measured latency is 12 milliseconds."
    with Session(engine) as db, db.begin():
        db.add(
            Document(
                id=document_id,
                sha256=uuid4().hex * 2,
                original_filename="fixture.pdf",
                size_bytes=10,
                s3_object_key=f"fixture/{document_id}",
                raw_content=content,
                processing_status="completed",
                created_by_id=actors[0].id,
            )
        )
        db.flush()
        db.add_all(
            LibraryPaper(user_id=actor.id, document_id=document_id) for actor in actors
        )
    yield engine, document_id, content, actors
    with Session(engine) as db, db.begin():
        db.execute(
            delete(ResearchItem).where(ResearchItem.target_document_id == document_id)
        )
        db.execute(delete(LibraryPaper).where(LibraryPaper.document_id == document_id))
        db.execute(delete(Document).where(Document.id == document_id))
    with admin.begin() as connection:
        connection.execute(
            text("DELETE FROM scholens.user_profiles WHERE user_id = ANY(:ids)"),
            {"ids": [a.id for a in actors]},
        )
        connection.execute(
            text("DELETE FROM auth.users WHERE id = ANY(:ids)"),
            {"ids": [a.id for a in actors]},
        )
    engine.dispose()
    admin.dispose()


def metadata(content, quotes):
    segment = next(evidence_segments(content))
    return PaperMetadataExtraction.model_validate(
        {
            "title": "Fixture",
            "highlights": [
                {
                    "text": quote,
                    "segment_id": segment.id,
                    "annotation": "Evidence explanation",
                    "type": "result",
                }
                for quote in quotes
            ],
        }
    )


def apply(fixture, payload, actor_index=0):
    engine, document_id, _, actors = fixture
    with Session(engine) as db, db.begin():
        return create_ai_annotations(
            db, document_id=document_id, metadata=payload, user=actors[actor_index]
        )


def test_partial_retry_preserves_previous_comments_and_other_users(evidence_database):
    engine, document_id, content, actors = evidence_database
    first = apply(
        evidence_database,
        metadata(
            content,
            [
                "efficient method improved results",
                "A fabricated paraphrase does not match.",
            ],
        ),
    )
    assert (first.total, first.anchored, first.skipped) == (2, 1, 1)
    second = apply(
        evidence_database,
        metadata(
            content,
            [
                "efficient method improved results",
                "measured latency is 12 milliseconds",
            ],
        ),
    )
    assert len(second.thread_ids) == 1 and second.already_present == 1
    other = apply(
        evidence_database, metadata(content, ["efficient method improved results"]), 1
    )
    assert len(other.thread_ids) == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AiAnnotationEvidence)) >= 3
        thread = db.get(AnnotationThread, first.thread_ids[0])
        assert thread.quote_text == "efﬁcient method improved results"
        assert thread.comments[0].content == "Evidence explanation"


def test_concurrent_duplicate_and_deleted_annotation_tombstone(evidence_database):
    engine, _, content, _ = evidence_database
    payload = metadata(content, ["efficient method improved results"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(evidence_database, payload), range(2)))
    assert sum(len(result.thread_ids) for result in results) == 1
    created = next(result.thread_ids[0] for result in results if result.thread_ids)
    with Session(engine) as db, db.begin():
        db.execute(delete(ResearchItem).where(ResearchItem.id == created))
    replay = apply(evidence_database, payload)
    assert not replay.thread_ids and replay.already_present == 1


def test_rollback_leaves_no_receipt_and_legacy_annotation_is_adopted(evidence_database):
    engine, document_id, content, actors = evidence_database
    payload = metadata(content, ["efficient method improved results"])
    with Session(engine) as db:
        first = create_ai_annotations(
            db, document_id=document_id, metadata=payload, user=actors[0]
        )
        assert len(first.thread_ids) == 1
        db.rollback()
    assert len(apply(evidence_database, payload).thread_ids) == 1
    quote = "measured latency is 12 milliseconds"
    start = content.index(quote)
    with Session(engine) as db, db.begin():
        legacy = research_repository.create_annotation_thread(
            db,
            document_id=document_id,
            user_id=actors[0].id,
            create=AnnotationThreadCreate(
                quote_text=quote,
                position=ParsedTextPosition(
                    start_offset=start, end_offset=start + len(quote)
                ),
                content_role=RoleType.ASSISTANT,
                color="blue",
                audience_type=ResearchAudienceType.PERSONAL,
                audience_project_id=None,
                initial_comment="Legacy comment retained",
            ),
        )
        legacy_id = legacy.id
    result = apply(evidence_database, metadata(content, [quote]))
    assert not result.thread_ids and result.already_present == 1
    with Session(engine) as db:
        assert (
            db.get(AnnotationThread, legacy_id).comments[0].content
            == "Legacy comment retained"
        )


def test_stale_source_and_revoked_access_create_no_annotations(evidence_database):
    engine, document_id, content, actors = evidence_database
    payload = metadata(content, ["efficient method improved results"])
    with Session(engine) as db, db.begin():
        db.get(Document, document_id).raw_content = content + " Updated."
    result = apply(evidence_database, payload)
    assert result.skipped == 1 and not result.thread_ids
    with Session(engine) as db, db.begin():
        db.execute(
            delete(LibraryPaper).where(
                LibraryPaper.document_id == document_id,
                LibraryPaper.user_id == actors[1].id,
            )
        )
    with pytest.raises(ValueError, match="document_not_found"):
        apply(
            evidence_database,
            metadata(content + " Updated.", ["efficient method improved results"]),
            1,
        )
