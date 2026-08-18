"""Regression tests for the bounded legacy data-repair commands."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from app.modules.papers.infrastructure.data_repair import ReprocessEnqueuer
from app.modules.papers.infrastructure.data_repair import SqlDataRepair


def _repair(
    db: MagicMock,
    *,
    enqueuer: ReprocessEnqueuer | Callable[..., bool] | None = None,
) -> SqlDataRepair:
    """Build the gateway with a stub composition enqueuer."""
    return SqlDataRepair(
        db,
        reprocess_enqueuer=enqueuer if enqueuer is not None else MagicMock(),
    )


def _source_job(*, job_id: UUID, requested_by_id: int = 1) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.requested_by_id = requested_by_id
    job.document_id = uuid4()
    job.correlation_id = uuid4()
    job.origin_operation_id = uuid4()
    job.project_id = None
    return job


def _document(*, sha256: str = "a" * 64, size_bytes: int = 2048) -> MagicMock:
    document = MagicMock()
    document.id = uuid4()
    document.sha256 = sha256
    document.original_filename = "paper.pdf"
    document.size_bytes = size_bytes
    document.s3_object_key = "documents/a" * 32
    return document


def test_fix_publish_dates_dry_run_only_counts_candidates() -> None:
    db = MagicMock()
    db.scalar.return_value = 3

    result = _repair(db).fix_publish_dates(batch_size=10, apply=False)

    assert result.candidates == 3
    assert result.fixed == 0
    db.execute.assert_not_called()


def test_fix_publish_dates_applies_bounded_update() -> None:
    db = MagicMock()
    db.scalar.return_value = 2
    document_id = uuid4()
    selected = MagicMock()
    selected.all.return_value = [(document_id, "2017-01-01")]
    db.execute.return_value = selected

    result = _repair(db).fix_publish_dates(batch_size=1, apply=True)

    assert result.candidates == 2
    assert result.fixed == 1
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert "UPDATE scholens.documents" in statements[1]
    assert db.execute.call_args_list[1].args[1][0]["publish_date"] == datetime(
        2017, 1, 1
    )


def test_fix_annotation_offsets_dry_run_reports_candidates() -> None:
    db = MagicMock()
    thread_id = uuid4()
    row = MagicMock()
    row.research_item_id = thread_id
    row.quote_text = "exact quote"
    row.start_offset = 4
    row.end_offset = 7
    row.position = None
    row.raw_content = "the exact quote is here"
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).fix_annotation_offsets(batch_size=10, apply=False)

    assert result.candidates == 1
    assert result.fixed == 0
    assert result.unresolved == 1


def test_fix_annotation_offsets_applies_exact_reanchor() -> None:
    db = MagicMock()
    thread_id = uuid4()
    row = MagicMock()
    row.research_item_id = thread_id
    row.quote_text = "exact quote"
    row.start_offset = 4
    row.end_offset = 7
    row.position = {"kind": "parsed_text", "page_number": 1}
    row.raw_content = "the exact quote is here"
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).fix_annotation_offsets(batch_size=10, apply=True)
    assert result.fixed == 1
    assert result.unresolved == 0
    statement, params = db.execute.call_args_list[1].args
    assert "UPDATE scholens.annotation_threads" in str(statement)
    assert params["start_offset"] == 4
    assert params["end_offset"] == 15
    assert json.loads(params["position"])["start_offset"] == 4


def test_fix_annotation_offsets_leaves_unresolvable_quotes_untouched() -> None:
    db = MagicMock()
    thread_id = uuid4()
    row = MagicMock()
    row.research_item_id = thread_id
    row.quote_text = "paraphrased text not in content"
    row.start_offset = 4
    row.end_offset = 7
    row.position = None
    row.raw_content = "completely different content"
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).fix_annotation_offsets(batch_size=10, apply=True)

    assert result.fixed == 0
    assert result.unresolved == 1
    assert len(db.execute.call_args_list) == 1  # no UPDATE issued


def test_purge_bad_citations_dry_run_samples_provider_rows() -> None:
    db = MagicMock()
    document_id = uuid4()
    row = MagicMock()
    row.id = document_id
    row.title = "Attention Is All You Need"
    row.publisher = "Shenzhen Medical Academy of Research and Translation"
    row.doi = "10.65215/ctdc8e75"
    row.journal = None
    row.field_provenance = {"publisher": {"filled_by": "get_paper_citation"}}
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).purge_bad_citations(batch_size=10, apply=False)

    assert result.candidates == 1
    assert result.purged == 0
    assert str(document_id) in result.sample_document_ids


def test_purge_bad_citations_apply_clears_provider_fields_keeps_provenance() -> None:
    db = MagicMock()
    document_id = uuid4()
    row = MagicMock()
    row.id = document_id
    row.title = "Attention Is All You Need"
    row.publisher = "Shenzhen Medical Academy of Research and Translation"
    row.doi = "10.65215/ctdc8e75"
    row.journal = "Medical Journal"
    row.field_provenance = {
        "publisher": {"filled_by": "get_paper_citation"},
        "doi": {"filled_by": "resolve_paper_citation"},
        "journal": {"filled_by": "get_paper_citation"},
    }
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).purge_bad_citations(batch_size=10, apply=True)

    assert result.candidates == 1
    assert result.purged == 1
    assert str(document_id) in result.sample_document_ids
    statement, params = db.execute.call_args_list[1].args
    rendered = str(statement)
    assert "publisher = NULL" in rendered
    assert "doi = NULL" in rendered
    assert "journal = NULL" in rendered
    assert params["document_id"] == document_id


def test_purge_bad_citations_apply_skips_non_provider_fields() -> None:
    db = MagicMock()
    document_id = uuid4()
    row = MagicMock()
    row.id = document_id
    row.title = "Attention Is All You Need"
    row.publisher = "Shenzhen Medical Academy of Research and Translation"
    row.doi = "10.65215/ctdc8e75"
    row.journal = None
    # Filled by an agentic/import path — not an external provider, so the
    # operator command must leave the row alone.
    row.field_provenance = {"publisher": {"filled_by": "zotero_import"}}
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).purge_bad_citations(batch_size=10, apply=True)

    assert result.candidates == 1
    assert result.purged == 0
    assert len(db.execute.call_args_list) == 1  # no UPDATE issued


def test_reprocess_contaminated_documents_dry_run_lists_jobs() -> None:
    db = MagicMock()
    job_id = uuid4()
    row = MagicMock()
    row.id = job_id
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected
    enqueuer = MagicMock()

    result = _repair(db, enqueuer=enqueuer).reprocess_contaminated_documents(
        batch_size=10, apply=False
    )

    assert result.candidates == 1
    assert result.reprocessed == 0
    assert str(job_id) in result.sample_job_ids
    enqueuer.assert_not_called()


def test_reprocess_contaminated_documents_apply_delegates_to_enqueuer() -> None:
    db = MagicMock()
    job_id = uuid4()
    row = MagicMock()
    row.id = job_id
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected
    source_job = _source_job(job_id=job_id)
    document = _document()
    db.get.side_effect = [source_job, document, None]
    enqueuer = MagicMock(return_value=True)

    result = _repair(db, enqueuer=enqueuer).reprocess_contaminated_documents(
        batch_size=10, apply=True
    )

    assert result.candidates == 1
    assert result.reprocessed == 1
    assert str(job_id) in result.sample_job_ids
    enqueuer.assert_called_once()
    kwargs = enqueuer.call_args.kwargs
    assert kwargs["db"] is db
    assert kwargs["source"] is source_job
    assert kwargs["document"] is document
    assert kwargs["reservation"] is None
    # The composition adapter owns job/dispatch/reservation creation; the
    # gateway must only locate the rows and delegate.
    document.processing_status.assert_not_called()


def test_reprocess_contaminated_documents_apply_replay_skips() -> None:
    db = MagicMock()
    job_id = uuid4()
    row = MagicMock()
    row.id = job_id
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected
    source_job = _source_job(job_id=job_id)
    document = _document()
    db.get.side_effect = [source_job, document, None]
    enqueuer = MagicMock(return_value=False)  # idempotency-key replay

    result = _repair(db, enqueuer=enqueuer).reprocess_contaminated_documents(
        batch_size=10, apply=True
    )

    assert result.reprocessed == 0
    enqueuer.assert_called_once()


def test_reprocess_contaminated_documents_apply_skips_missing_document() -> None:
    db = MagicMock()
    job_id = uuid4()
    row = MagicMock()
    row.id = job_id
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected
    db.get.side_effect = [None]
    enqueuer = MagicMock()

    result = _repair(db, enqueuer=enqueuer).reprocess_contaminated_documents(
        batch_size=10, apply=True
    )

    assert result.candidates == 1
    assert result.reprocessed == 0
    enqueuer.assert_not_called()
