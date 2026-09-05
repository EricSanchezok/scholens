from unittest.mock import MagicMock
from uuid import uuid4

from scholens_ai import semantic_source_digest

from app.modules.papers.application.maintenance import PassageEmbeddingWrite
from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill
from app.modules.papers.infrastructure.search_repository import DocumentSearchRepository


def test_backfill_uses_bounded_runtime_dml_and_sanitizes_nulls() -> None:
    document_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = 2
    selected = MagicMock()
    selected.all.return_value = [(document_id, "alpha\x00beta")]
    db.execute.return_value = selected

    result = SqlPassageBackfill(db).backfill(batch_size=1, apply=True)

    assert result.candidates == 2
    assert result.indexed_documents == 1
    assert result.indexed_passages == 1
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert all("ALTER TABLE" not in statement for statement in statements)
    assert all(
        "UPDATE scholens.document_passages" not in statement for statement in statements
    )
    assert "LIMIT :limit" in statements[0]
    assert db.execute.call_args_list[0].args[1] == {"limit": 1}
    inserted = db.execute.call_args_list[1].args[1]
    assert inserted[0]["content"] == "alphabeta"


def test_backfill_dry_run_only_counts_candidates() -> None:
    db = MagicMock()
    db.scalar.return_value = 7

    result = SqlPassageBackfill(db).backfill(batch_size=2, apply=False)

    assert result.candidates == 7
    assert result.indexed_documents == 0
    assert result.indexed_passages == 0
    db.execute.assert_not_called()


def test_embedding_candidates_are_bounded_and_digest_current_content() -> None:
    document_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = 3
    selected = MagicMock()
    selected.all.return_value = [(11, document_id, 4, "current passage")]
    db.execute.return_value = selected

    snapshot = SqlPassageBackfill(db).embedding_candidates(batch_size=1)

    assert snapshot.candidates == 3
    assert len(snapshot.items) == 1
    assert snapshot.items[0].source_digest == semantic_source_digest("current passage")
    statement = str(db.execute.call_args.args[0])
    assert "LIMIT :param_1" in statement
    assert "embedding_model_revision" in statement


def test_embedding_apply_revalidates_digest_before_writing() -> None:
    document_id = uuid4()
    db = MagicMock()
    db.scalar.side_effect = ["current passage", "changed passage"]
    current_digest = semantic_source_digest("current passage")
    records = (
        PassageEmbeddingWrite(
            passage_id=11,
            document_id=document_id,
            start_line=4,
            source_digest=current_digest,
            embedding=(1.0,) + (0.0,) * 383,
        ),
        PassageEmbeddingWrite(
            passage_id=12,
            document_id=document_id,
            start_line=8,
            source_digest=current_digest,
            embedding=(1.0,) + (0.0,) * 383,
        ),
    )

    indexed, stale = SqlPassageBackfill(db).apply_embeddings(
        records=records,
        model_revision="model-v1",
    )

    assert (indexed, stale) == (1, 1)
    update_statements = [
        str(call.args[0])
        for call in db.execute.call_args_list
        if str(call.args[0]).startswith("UPDATE")
    ]
    assert len(update_statements) == 1
    assert "embedding_source_digest" in update_statements[0]


def test_passage_index_rejects_an_artifact_for_different_content() -> None:
    db = MagicMock()

    DocumentSearchRepository().replace_passage_index(
        db,
        document_id=uuid4(),
        raw_content="current passage",
        embeddings={"a" * 64: [1.0] + [0.0] * 383},
        embedding_model_revision="model-v1",
    )

    rows = db.execute.call_args_list[1].args[1]
    assert rows[0]["embedding"] is None
    assert rows[0]["embedding_model_revision"] is None
    assert rows[0]["embedding_source_digest"] is None
