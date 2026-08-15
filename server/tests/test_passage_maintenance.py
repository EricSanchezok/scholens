from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill


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
