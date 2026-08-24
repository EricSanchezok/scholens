"""Regression tests for the bounded legacy data-repair commands."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Callable
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner
from app.modules.papers.infrastructure.data_repair import ReprocessEnqueuer
from app.modules.papers.infrastructure.data_repair import SqlDataRepair
from app.bootstrap.adapters.data_repair_jobs import (
    enqueue_reprocess_job,
    recover_unclaimed_pdf_job,
)
from app.cli import cli


def _repair(
    db: MagicMock,
    *,
    enqueuer: ReprocessEnqueuer | Callable[..., UUID | None] | None = None,
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
    job.operation = "pdf_process"
    return job


def _document(*, sha256: str = "a" * 64, size_bytes: int = 2048) -> MagicMock:
    document = MagicMock()
    document.id = uuid4()
    document.sha256 = sha256
    document.original_filename = "paper.pdf"
    document.size_bytes = size_bytes
    document.s3_object_key = f"documents/{sha256}/source.pdf"
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
    new_job_id = uuid4()
    enqueuer = MagicMock(return_value=new_job_id)

    result = _repair(db, enqueuer=enqueuer).reprocess_contaminated_documents(
        batch_size=10, apply=True
    )

    assert result.candidates == 1
    assert result.reprocessed == 1
    assert result.sample_job_ids == (str(new_job_id),)
    assert result.enqueued == 1
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
    enqueuer = MagicMock(return_value=None)  # idempotency-key replay

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


def test_unicode_replacement_repair_dry_run_is_bounded_and_read_only() -> None:
    db = MagicMock()
    row = SimpleNamespace(
        document_id=uuid4(),
        source_job_id=uuid4(),
        content_bytes=128,
    )
    selected = MagicMock()
    selected.all.return_value = [row]
    exhausted = MagicMock()
    exhausted.all.return_value = []
    db.execute.side_effect = [selected, exhausted]
    enqueuer = MagicMock()

    result = _repair(
        db,
        enqueuer=enqueuer,
    ).reprocess_unicode_replacement_documents(batch_size=10, apply=False)

    assert result.candidates == 1
    assert result.reprocessed == 0
    assert result.sample_job_ids == ()
    assert result.sample_document_ids == (str(row.document_id),)
    assert result.scanned == 1
    assert result.work_bytes == 128
    enqueuer.assert_not_called()
    statement = str(db.execute.call_args.args[0])
    assert "position(U&'\\FFFD' in document.raw_content) > 0" in statement
    assert "NOT EXISTS" in statement
    terminal_guard = statement.split("AND NOT EXISTS (", 1)[1].split(
        "AND COALESCE((", 1
    )[0]
    assert "repair.status IN ('pending', 'running')" in terminal_guard
    assert "repair.status = 'completed'" in terminal_guard
    assert "repair.id = source.id" in terminal_guard
    assert "repair.result" not in terminal_guard
    assert "repair_source_job_id" in terminal_guard


def test_unicode_repair_cli_rejects_oversized_batch_before_execution() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "maintenance",
            "reprocess-replacement-character-documents",
            "--actor-email",
            "admin@example.com",
            "--batch-size",
            "51",
        ],
    )

    assert result.exit_code == 2
    assert "51 is not in the range 1<=x<=50" in result.output


def test_unicode_replacement_repair_apply_binds_source_content() -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.project_id = uuid4()
    document = _document()
    document.id = source.document_id
    document.processing_job_id = source.id
    document.raw_content = "damaged \ufffd evidence"
    row = SimpleNamespace(
        document_id=document.id,
        source_job_id=source.id,
        content_bytes=len(document.raw_content.encode("utf-8")),
    )
    selected = MagicMock()
    selected.all.return_value = [row]
    exhausted = MagicMock()
    exhausted.all.return_value = []
    no_attempts = MagicMock()
    no_attempts.one.return_value = SimpleNamespace(blocked=False, highest_attempt=0)
    db.execute.side_effect = [selected, exhausted, no_attempts]
    db.scalar.side_effect = [source, document]
    db.get.return_value = None
    new_job_id = uuid4()
    enqueuer = MagicMock(return_value=new_job_id)

    result = _repair(
        db,
        enqueuer=enqueuer,
    ).reprocess_unicode_replacement_documents(batch_size=10, apply=True)

    assert result.reprocessed == 1
    assert result.sample_job_ids == (str(new_job_id),)
    kwargs = enqueuer.call_args.kwargs
    assert kwargs["repair_revision"] == "unicode-replacement-v1"
    assert (
        kwargs["source_content_digest"]
        == hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest()
    )
    assert kwargs["repair_attempt"] == 1


@pytest.mark.parametrize(
    ("blocked", "highest_attempt", "expected_attempt"),
    [
        (False, 0, 1),
        (False, 1, 2),
        (False, 2, 3),
        (False, 3, None),
        (True, 0, None),
    ],
)
def test_unicode_repair_attempts_are_bounded_and_terminal_outcome_aware(
    blocked: bool,
    highest_attempt: int,
    expected_attempt: int | None,
) -> None:
    db = MagicMock()
    selected = MagicMock()
    selected.one.return_value = SimpleNamespace(
        blocked=blocked,
        highest_attempt=highest_attempt,
    )
    db.execute.return_value = selected

    attempt = _repair(db)._next_unicode_repair_attempt(
        document_id=uuid4(),
        source_job_id=uuid4(),
        source_content_digest="a" * 64,
    )

    assert attempt == expected_attempt
    state_sql = str(db.execute.call_args.args[0])
    assert "bool_or(repair.status IN ('pending', 'running', 'completed'))" in state_sql
    assert "repair.status IN ('failed', 'cancelled')" in state_sql


def test_unicode_repair_selection_uses_keyset_locks_and_byte_budget() -> None:
    db = MagicMock()
    oversized = SimpleNamespace(
        document_id=uuid4(),
        source_job_id=uuid4(),
        content_bytes=33 * 1024 * 1024,
    )
    eligible = SimpleNamespace(
        document_id=uuid4(),
        source_job_id=uuid4(),
        content_bytes=1024,
    )
    page = MagicMock()
    page.all.return_value = [oversized, eligible]
    exhausted = MagicMock()
    exhausted.all.return_value = []
    db.execute.side_effect = [page, exhausted]

    result = _repair(db).reprocess_unicode_replacement_documents(
        batch_size=2,
        apply=True,
    )

    # The oversized row is never materialized as raw text or sent to Jobs.
    assert result.candidates == 1
    assert result.scanned == 2
    assert result.skipped >= 1
    assert result.work_bytes == 1024
    candidate_sql = str(db.execute.call_args_list[0].args[0])
    assert "octet_length(document.raw_content)" in candidate_sql
    assert "octet_length(document.raw_content) <= :max_document_bytes" in candidate_sql
    assert "CAST(:after_id AS uuid) IS NULL" in candidate_sql
    assert "document.id > CAST(:after_id AS uuid)" in candidate_sql
    assert "FOR UPDATE OF document SKIP LOCKED" in candidate_sql


def test_unicode_repair_savepoint_failure_does_not_abort_later_candidate() -> None:
    db = MagicMock()
    gateway = _repair(db)
    first = SimpleNamespace(document_id=uuid4(), source_job_id=uuid4())
    second = SimpleNamespace(document_id=uuid4(), source_job_id=uuid4())
    new_job_id = uuid4()
    gateway._unicode_repair_candidates = MagicMock(  # type: ignore[method-assign]
        return_value=([first, second], 2, 0, 2048)
    )
    gateway._enqueue_unicode_repair = MagicMock(  # type: ignore[method-assign]
        side_effect=[RuntimeError("pdf_repair_source_content_changed"), new_job_id]
    )

    result = gateway.reprocess_unicode_replacement_documents(
        batch_size=2,
        apply=True,
    )

    assert result.enqueued == 1
    assert result.sample_job_ids == (str(new_job_id),)
    assert result.skipped == 1
    assert db.begin_nested.call_count == 2


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
    source.project_id = uuid4()
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
    assert enqueue.call_args.kwargs["request"].project_id == source.project_id


def test_unicode_repair_enqueues_metadata_free_versioned_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    source.project_id = uuid4()
    document = _document()
    document.raw_content = "damaged \ufffd evidence"
    document.processing_job_id = source.id
    reservation = MagicMock()
    reservation.superseded_by_id = None
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
    digest = hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest()

    assert enqueue_reprocess_job(
        db=db,
        source=source,
        document=document,
        reservation=reservation,
        repair_revision="unicode-replacement-v1",
        source_content_digest=digest,
        repair_attempt=1,
    )

    request = enqueue.call_args.kwargs["request"]
    assert request.payload["repair_kind"] == "unicode_replacement"
    assert request.payload["repair_source_job_id"] == str(source.id)
    assert request.payload["repair_attempt"] == 1
    assert request.payload["job_visibility"] == "maintenance"
    assert request.payload["skip_metadata_extraction"] is True
    assert request.project_id is None
    assert request.task_name == "repair_pdf_text"
    assert set(request.task_kwargs) == {
        "job_id",
        "document_id",
        "s3_key",
        "callback_url",
        "claim_url",
        "progress_url",
        "mineru_credential_url",
        "repair_revision",
        "source_job_id",
        "source_content_digest",
        "repair_attempt",
    }
    assert request.task_kwargs["repair_revision"] == "unicode-replacement-v1"
    assert request.task_kwargs["repair_attempt"] == 1
    assert request.idempotency_key.endswith(f":{digest}:attempt:1")
    assert f":{source.id}:{digest}:" in request.idempotency_key
    assert len(request.idempotency_key) <= 255
    assert document.processing_status == "completed"
    assert document.processing_job_id == source.id
    assert document.parser_quality == "text_only"
    assert document.parser_warning_code == "unicode_replacement_detected"
    assert reservation.superseded_by_id is None


def test_unicode_repair_retry_uses_distinct_digest_bound_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    source = _source_job(job_id=uuid4())
    document = _document()
    document.raw_content = "damaged \ufffd evidence"
    digest = hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest()
    enqueue = MagicMock(
        side_effect=[
            SimpleNamespace(created=True, job=MagicMock()),
            SimpleNamespace(created=True, job=MagicMock()),
        ]
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.job_repository.enqueue",
        enqueue,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.get_webhook_base_url",
        lambda: "http://127.0.0.1:7301",
    )

    for attempt in (1, 2):
        assert (
            enqueue_reprocess_job(
                db=db,
                source=source,
                document=document,
                reservation=None,
                repair_revision="unicode-replacement-v1",
                source_content_digest=digest,
                repair_attempt=attempt,
            )
            is not None
        )

    requests = [call.kwargs["request"] for call in enqueue.call_args_list]
    assert requests[0].idempotency_key.endswith(f":{digest}:attempt:1")
    assert requests[1].idempotency_key.endswith(f":{digest}:attempt:2")
    assert requests[0].idempotency_key != requests[1].idempotency_key


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
