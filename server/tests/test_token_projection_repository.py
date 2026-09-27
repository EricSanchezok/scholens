"""Real PostgreSQL proofs for atomic adoption and N-1 source invalidation."""

import base64
import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session
from scholens_ai.passages import (
    PassageEmbeddingRecord,
    encode_passage_embedding_artifact,
)
from scholens_ai.token_projection import TokenProjection, TokenSpan

from app.database import models as _models  # noqa: F401
from app.modules.papers.infrastructure.models import (
    Document,
    DocumentPassage,
    DocumentTokenPassage,
    DocumentTokenProjection,
)
from app.modules.papers.infrastructure.token_projection import (
    TokenProjectionRepository,
    searchable_passages,
)


@pytest.fixture
def database():
    url = os.getenv("SCHOLENS_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("isolated PostgreSQL URL is not configured")
    engine = create_engine(url)
    doc_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(
            Document(
                id=doc_id,
                sha256=uuid4().hex * 2,
                original_filename="projection.pdf",
                size_bytes=1,
                s3_object_key=f"tests/{doc_id}.pdf",
                raw_content="alpha alpha",
                processing_status="completed",
            )
        )
        db.flush()
        db.add(
            DocumentPassage(
                document_id=doc_id, start_line=1, end_line=1, content="alpha alpha"
            )
        )
    yield engine, doc_id
    with Session(engine) as db, db.begin():
        db.execute(delete(Document).where(Document.id == doc_id))
    engine.dispose()


def projection():
    digest = hashlib.sha256(b"alpha").hexdigest()
    binary = encode_passage_embedding_artifact(
        model_revision="test-v1",
        records=[PassageEmbeddingRecord(digest, (1.0,) + (0.0,) * 383)],
    )
    return TokenProjection(
        content_digest=hashlib.sha256(b"alpha alpha").hexdigest(),
        model_revision="test-v1",
        spans=[
            TokenSpan(start=0, end=5, tokens=1),
            TokenSpan(start=6, end=11, tokens=1),
        ],
        vectors=base64.b64encode(binary).decode(),
    )


def test_atomic_adoption_keeps_legacy_and_rolls_back_as_one_unit(database):
    engine, doc_id = database
    result = projection()
    with Session(engine) as db, db.begin():
        assert TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=result
        )
    with Session(engine) as db, db.begin():
        rows = db.scalars(
            select(DocumentTokenPassage)
            .where(DocumentTokenPassage.document_id == doc_id)
            .order_by(DocumentTokenPassage.ordinal)
        ).all()
        assert [(row.start_line, row.start_offset) for row in rows] == [(1, 0), (1, 6)]
        assert db.scalar(
            select(DocumentPassage.id).where(DocumentPassage.document_id == doc_id)
        )
        assert db.get(DocumentTokenProjection, (doc_id, "test-v1")).passage_count == 2
    with pytest.raises(RuntimeError), Session(engine) as db, db.begin():
        assert TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=result
        )
        raise RuntimeError("crash_before_commit")
    with Session(engine) as db:
        assert db.get(DocumentTokenProjection, (doc_id, "test-v1")).passage_count == 2


def test_n_minus_one_text_update_invalidates_head_and_stale_result_cannot_replace_it(
    database,
):
    engine, doc_id = database
    with Session(engine) as db, db.begin():
        assert TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=projection()
        )
        db.execute(
            text("UPDATE scholens.documents SET raw_content = :body WHERE id = :id"),
            {"body": "changed", "id": doc_id},
        )
    with Session(engine) as db, db.begin():
        assert (
            db.get(Document, doc_id).content_digest
            == hashlib.sha256(b"changed").hexdigest()
        )
        assert not TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=projection()
        )
        assert (
            db.get(DocumentTokenProjection, (doc_id, "test-v1")).content_digest
            != db.get(Document, doc_id).content_digest
        )


def test_unrelated_metadata_update_preserves_digest_and_projection(database):
    engine, doc_id = database
    with Session(engine) as db, db.begin():
        assert TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=projection()
        )
        db.execute(
            text(
                "UPDATE scholens.documents SET summary = 'new summary' WHERE id = :id"
            ),
            {"id": doc_id},
        )
    with Session(engine) as db:
        assert db.get(Document, doc_id).content_digest == projection().content_digest
        assert (
            db.get(DocumentTokenProjection, (doc_id, "test-v1")).content_digest
            == projection().content_digest
        )


def test_search_uses_one_current_projection_without_old_revision_or_stale_fallback(
    database,
):
    engine, doc_id = database
    with Session(engine) as db, db.begin():
        assert TokenProjectionRepository(db).adopt(
            document_id=doc_id, projection=projection()
        )
    passages = searchable_passages(model_revision="test-v1").c
    statement = select(passages.start_line, passages.content).where(
        passages.document_id == doc_id
    )
    with Session(engine) as db, db.begin():
        assert db.execute(statement).all() == [(1, "alpha"), (1, "alpha")]
        other = searchable_passages(model_revision="not-adopted").c
        assert db.scalars(
            select(other.content).where(other.document_id == doc_id)
        ).all() == ["alpha alpha"]
        db.execute(
            text("UPDATE scholens.documents SET raw_content = 'new' WHERE id = :id"),
            {"id": doc_id},
        )
        assert db.execute(statement).all() == []
