"""Regression tests for the bounded legacy data-repair commands."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Callable
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.papers.infrastructure.data_repair import ReprocessEnqueuer
from app.modules.papers.infrastructure.data_repair import SqlDataRepair
from app.bootstrap.adapters.data_repair_jobs import (
    enqueue_reprocess_job,
    recover_unclaimed_pdf_job,
)


def _repair(
    db: MagicMock,
    *,
    enqueuer: ReprocessEnqueuer | Callable[..., bool] | None = None,
    recoverer: Callable[..., None] | None = None,
) -> SqlDataRepair:
    """Build the gateway with a stub composition enqueuer."""
    return SqlDataRepair(
        db,
        reprocess_enqueuer=enqueuer if enqueuer is not None else MagicMock(),
        stuck_job_recoverer=recoverer if recoverer is not None else MagicMock(),
    )


def _source_job(*, job_id: UUID, requested_by_id: int = 1) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.requested_by_id = requested_by_id
    job.document_id = uuid4()
    job.correlation_id = uuid4()
    job.origin_operation_id = uuid4()
    job.project_id = None
    job.status = "completed"
    return job


def _document(*, sha256: str = "a" * 64, size_bytes: int = 2048) -> MagicMock:
    document = MagicMock()
    document.id = uuid4()
    document.sha256 = sha256
    document.original_filename = "paper.pdf"
    document.size_bytes = size_bytes
    document.s3_object_key = "documents/a" * 32
    document.processing_status = "completed"
    return document


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


def test_fix_annotation_offsets_leaves_ambiguous_repeated_quote_untouched() -> None:
    db = MagicMock()
    row = MagicMock()
    row.research_item_id = uuid4()
    row.quote_text = "same quote"
    row.position = None
    row.raw_content = "same quote then same quote"
    selected = MagicMock()
    selected.all.return_value = [row]
    db.execute.return_value = selected

    result = _repair(db).fix_annotation_offsets(batch_size=10, apply=True)

    assert result.fixed == 0
    assert result.unresolved == 1
    assert len(db.execute.call_args_list) == 1


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
    statement = str(db.execute.call_args.args[0])
    assert "job.status = 'completed'" in statement
    assert "document.processing_status = 'completed'" in statement
    assert "document.processing_job_id = job.id" in statement


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
    document.processing_job_id = source_job.id
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
    assert document.processing_status == "completed"


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
    document.processing_job_id = source_job.id
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


def test_recover_stuck_paper_ingestion_is_dry_run_by_default() -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.status = "pending"
    db.scalar.return_value = source
    recoverer = MagicMock()

    result = _repair(db, recoverer=recoverer).recover_stuck_paper_ingestion(
        job_id=source.id,
        min_age_seconds=3600,
        apply=False,
    )

    assert result.candidates == 1
    assert result.reprocessed == 0
    assert result.sample_job_ids == (str(source.id),)
    recoverer.assert_not_called()


def test_recover_stuck_paper_ingestion_apply_delegates_locked_candidate() -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.status = "pending"
    db.scalar.return_value = source
    recoverer = MagicMock()

    result = _repair(db, recoverer=recoverer).recover_stuck_paper_ingestion(
        job_id=source.id,
        min_age_seconds=3600,
        apply=True,
    )

    assert result.reprocessed == 1
    recoverer.assert_called_once_with(db, source)


def test_reprocess_existing_document_does_not_reserve_storage_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    document = _document(size_bytes=8 * 1024)
    persisted_job = MagicMock()
    enqueue = MagicMock(return_value=SimpleNamespace(created=True, job=persisted_job))
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.job_repository.enqueue",
        enqueue,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.get_webhook_base_url",
        lambda: "http://127.0.0.1:7301",
    )

    assert enqueue_reprocess_job(
        db=db,
        source=source,
        document=document,
        reservation=None,
    )

    created_reservation = db.add.call_args.args[0]
    assert created_reservation.reserved_size_kb == 0
    assert created_reservation.reserved_reference_count == 0


def test_unclaimed_pdf_recovery_supersedes_source_and_preserves_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.status = "pending"
    source.operation = "pdf_process"
    source.payload = {"recovery_attempt": 0}
    document = _document()
    document.id = source.document_id
    document.processing_status = "processing"
    document.processing_job_id = source.id
    reservation = MagicMock()
    db.scalar.return_value = document
    db.get.return_value = reservation
    persisted_job = MagicMock()
    enqueue = MagicMock(return_value=SimpleNamespace(created=True, job=persisted_job))
    fail = MagicMock(return_value=(source, True))
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.job_repository.enqueue",
        enqueue,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.job_repository.fail",
        fail,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.get_webhook_base_url",
        lambda: "http://127.0.0.1:7301",
    )

    recover_unclaimed_pdf_job(db, source)

    request = enqueue.call_args.kwargs["request"]
    assert request.payload["recovery_attempt"] == 1
    assert request.task_kwargs["claim_url"].endswith(f"/{request.job_id}/claim")
    assert reservation.superseded_by_id == request.job_id
    assert document.processing_job_id == request.job_id
    assert document.processing_status == "processing"
    fail.assert_called_once_with(
        db,
        job_id=source.id,
        error_code="paper_ingestion_claim_failed",
        result={"recovered_by_job_id": str(request.job_id)},
    )


def test_second_unclaimed_pdf_failure_becomes_terminal_without_another_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.status = "pending"
    source.operation = "pdf_process"
    source.payload = {"recovery_attempt": 1}
    document = _document()
    document.id = source.document_id
    document.processing_status = "processing"
    document.processing_job_id = source.id
    db.scalar.return_value = document
    fail = MagicMock(return_value=(source, True))
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.job_repository.fail",
        fail,
    )
    enqueue = MagicMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.enqueue_reprocess_job",
        enqueue,
    )

    recover_unclaimed_pdf_job(db, source)

    enqueue.assert_not_called()
    assert document.processing_status == "failed"
    assert document.parser_warning_code == "processing_failed"
