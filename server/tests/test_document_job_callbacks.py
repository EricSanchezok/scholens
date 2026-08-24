"""PDF completion stores paper-owned metadata without manufacturing chats."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.adapters import (
    document_job_callbacks,
    document_text_repair_callbacks,
)
from app.modules.jobs.application.contracts import (
    PDFProcessingResult,
    PdfProcessingWebhookData,
)
from app.modules.jobs.infrastructure.repository import PersistedJob
from app.modules.papers.application.contracts.extraction import (
    PaperMetadataExtraction,
    ResponseCitation,
)
from app.shared.application import (
    Actor,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.shared.domain.enums import (
    DocumentProcessingStatus,
    JobOperation,
    JobStatus,
)

from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.bootstrap.workflows.pdf_postprocess import PdfPostprocessResolution


class _AvailableLock:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.released = False

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


@pytest.fixture(autouse=True)
def _stub_repair_storage_deletion(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    scheduled = MagicMock()
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "schedule_storage_deletion",
        scheduled,
    )
    return scheduled


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


@pytest.mark.parametrize(
    ("reason", "progress_code", "expected"),
    [
        (
            "paper_ingestion_metadata_failed",
            "parsing",
            "paper_ingestion_metadata_failed",
        ),
        ("pdf_content_insufficient", "parsing", "pdf_content_insufficient"),
        ("mineru_response_unsafe", "parsing", "mineru_response_unsafe"),
        (
            "provider leaked a private diagnostic",
            "indexing",
            "paper_ingestion_indexing_failed",
        ),
        (
            "provider leaked a private diagnostic",
            None,
            "paper_ingestion_parsing_failed",
        ),
    ],
)
def test_pdf_failure_code_preserves_safe_codes_and_hides_private_diagnostics(
    reason: str,
    progress_code: str | None,
    expected: str,
) -> None:
    assert (
        document_job_callbacks._safe_pdf_failure_code(
            reason=reason,
            progress_code=progress_code,
        )
        == expected
    )


def _unicode_repair_job(
    *,
    job_id,
    source_job_id,
    document_id,
    source_content: str,
    source_sha256: str,
    progress_code: str | None = "parsing",
    repair_revision: str = "unicode-replacement-v1",
):
    return SimpleNamespace(
        id=job_id,
        document_id=document_id,
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
        progress_code=progress_code,
        payload={
            "repair_kind": "unicode_replacement",
            "repair_revision": repair_revision,
            "repair_source_job_id": str(source_job_id),
            "repair_source_content_digest": hashlib.sha256(
                source_content.encode("utf-8")
            ).hexdigest(),
            "repair_attempt": 1,
            "job_visibility": "maintenance",
            "content_sha256": source_sha256,
        },
    )


def _successful_unicode_repair_result(
    *,
    job_id,
    source_sha256: str,
    raw_content: str,
) -> PDFProcessingResult:
    prefix = f"documents/{source_sha256}/repairs/unicode-replacement-v1/{job_id}/"
    return PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content=raw_content,
        page_offset_map={1: [0, len(raw_content)]},
        s3_object_key=f"documents/{source_sha256}/source.pdf",
        parser_markdown_s3_key=f"{prefix}canonical.md",
        parser_backend="markitdown",
        parser_quality="text_only",
        parser_version="repair-test",
        parser_warning_code="markitdown_fallback",
    )


def _reanchor_preflight(*threads: SimpleNamespace) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            thread_id=uuid4(),
            quote_bytes=len(thread.quote_text.encode("utf-8")),
            position_bytes=128,
        )
        for thread in threads
    ]


def test_unicode_repair_atomically_reanchors_and_rebuilds_passages(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "a" * 64
    source_content = (
        "Introduction damaged \ufffd evidence. The unique quote appears later."
    )
    repaired_content = (
        "Introduction damaged √ evidence. The unique quote appears later."
    )
    document = SimpleNamespace(
        id=document_id,
        sha256=source_sha256,
        s3_object_key=f"documents/{source_sha256}/source.pdf",
        raw_content=source_content,
        processing_job_id=source_job_id,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="text_only",
        parser_warning_code="unicode_replacement_detected",
        parser_markdown_s3_key=(
            f"documents/{source_sha256}/jobs/{source_job_id}/canonical.md"
        ),
        parser_archive_s3_key=None,
    )
    thread = SimpleNamespace(
        quote_text="unique quote",
        start_offset=0,
        end_offset=12,
        page_number=1,
        position={
            "kind": "parsed_text",
            "start_offset": 0,
            "end_offset": 12,
            "page_number": 1,
        },
    )
    unmapped_thread = SimpleNamespace(
        quote_text="Introduction",
        start_offset=0,
        end_offset=12,
        page_number=7,
        position={
            "kind": "parsed_text",
            "start_offset": 0,
            "end_offset": 12,
            "page_number": 7,
        },
    )
    db = MagicMock()
    db.scalar.return_value = document
    db.execute.return_value.all.return_value = _reanchor_preflight(
        thread,
        unmapped_thread,
    )
    db.scalars.return_value.all.return_value = [thread, unmapped_thread]
    db.get.return_value = None
    update_canonical = MagicMock(return_value=document)
    replace_passages = MagicMock()
    monkeypatch.setattr(
        document_text_repair_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    monkeypatch.setattr(
        document_text_repair_callbacks.document_search_repository,
        "replace_passage_index",
        replace_passages,
    )
    complete_job = MagicMock(return_value=True)
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "_complete_pdf_job",
        complete_job,
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content=repaired_content,
        page_offset_map={1: [5, 30], 2: [30, len(repaired_content)]},
        s3_object_key=document.s3_object_key,
        parser_markdown_s3_key=(
            f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
            f"{job_id}/canonical.md"
        ),
        parser_backend="markitdown",
        parser_quality="text_only",
        parser_version="repair-test",
        parser_warning_code="markitdown_fallback",
    )

    handled = document_text_repair_callbacks.complete_unicode_repair(
        db=db,
        durable_job=_unicode_repair_job(
            job_id=job_id,
            source_job_id=source_job_id,
            document_id=document_id,
            source_content=source_content,
            source_sha256=source_sha256,
        ),
        result=result,
        post_commit=(),
    )

    update = update_canonical.call_args.kwargs["update"]
    assert update_canonical.call_args.kwargs["user"] is None
    assert update.raw_content == repaired_content
    assert "title" not in update.model_dump(exclude_unset=True)
    assert thread.start_offset == repaired_content.index("unique quote")
    assert thread.position["end_offset"] == thread.end_offset
    assert thread.page_number == 2
    assert thread.position["page_number"] == 2
    assert unmapped_thread.page_number is None
    assert unmapped_thread.position["page_number"] is None
    replace_passages.assert_called_once_with(
        db,
        document_id=document_id,
        raw_content=repaired_content,
    )
    assert handled.value["repair_applied"] is True
    persisted_result = complete_job.call_args.kwargs["persisted_result"]
    assert "raw_content" not in persisted_result
    assert "page_offset_map" not in persisted_result
    assert (
        persisted_result["candidate_content_sha256"]
        == hashlib.sha256(repaired_content.encode("utf-8")).hexdigest()
    )
    assert persisted_result["repair_outcome"] == "applied"
    deletion = _stub_repair_storage_deletion.call_args
    assert set(deletion.kwargs["object_keys"]) == {
        f"documents/{source_sha256}/jobs/{source_job_id}/canonical.md"
    }
    assert deletion.kwargs["idempotency_key"].endswith(":replaced")


def test_unicode_repair_preserves_canonical_content_when_reanchor_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "b" * 64
    surrounding = "stable surrounding paper evidence " * 20
    source_content = f"{surrounding}damaged \ufffd unique quote {surrounding}"
    repaired_content = (
        f"{surrounding}damaged √ unique quote then unique quote {surrounding}"
    )
    document = SimpleNamespace(
        id=document_id,
        sha256=source_sha256,
        s3_object_key=f"documents/{source_sha256}/source.pdf",
        raw_content=source_content,
        processing_job_id=source_job_id,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="text_only",
        parser_warning_code="unicode_replacement_detected",
        parser_markdown_s3_key=(
            f"documents/{source_sha256}/jobs/{source_job_id}/canonical.md"
        ),
        parser_archive_s3_key=None,
    )
    thread = SimpleNamespace(
        quote_text="unique quote",
        page_number=1,
        position={"kind": "parsed_text", "start_offset": 10, "end_offset": 22},
    )
    db = MagicMock()
    db.scalar.return_value = document
    db.execute.return_value.all.return_value = _reanchor_preflight(thread)
    db.scalars.return_value.all.return_value = [thread]
    db.get.return_value = None
    update_canonical = MagicMock()
    monkeypatch.setattr(
        document_text_repair_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "_complete_pdf_job",
        MagicMock(return_value=True),
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content=repaired_content,
        page_offset_map={1: [0, len(repaired_content)]},
        s3_object_key=document.s3_object_key,
        parser_markdown_s3_key=(
            f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
            f"{job_id}/canonical.md"
        ),
        parser_backend="markitdown",
        parser_quality="text_only",
        parser_version="repair-test",
        parser_warning_code="markitdown_fallback",
    )

    handled = document_text_repair_callbacks.complete_unicode_repair(
        db=db,
        durable_job=_unicode_repair_job(
            job_id=job_id,
            source_job_id=source_job_id,
            document_id=document_id,
            source_content=source_content,
            source_sha256=source_sha256,
        ),
        result=result,
        post_commit=(),
    )

    update_canonical.assert_not_called()
    assert document.raw_content == source_content
    assert document.processing_job_id == source_job_id
    assert handled.value["repair_applied"] is False
    assert handled.value["repair_reason"] == "annotation_reanchor_unsafe"
    assert set(_stub_repair_storage_deletion.call_args.kwargs["object_keys"]) == {
        f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
        f"{job_id}/canonical.md",
        f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
        f"{job_id}/mineru-result.zip",
    }


def test_unicode_repair_reanchor_planning_rejects_unbounded_scan_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    threads = [
        SimpleNamespace(
            quote_text=f"quote-{index}",
            position={"kind": "parsed_text", "start_offset": 0, "end_offset": 1},
        )
        for index in range(3)
    ]
    db = MagicMock()
    db.execute.return_value.all.return_value = _reanchor_preflight(*threads)
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "UNICODE_REPAIR_MAX_REANCHOR_SCAN_CHARACTERS",
        100,
    )

    planned = document_text_repair_callbacks._planned_parsed_text_reanchors(
        db=db,
        document_id=document_id,
        raw_content="candidate" * 100,
        page_offset_map=None,
    )

    assert planned is None
    statement = db.execute.call_args.args[0]
    assert "LIMIT" in str(statement).upper()
    db.scalars.assert_not_called()


def test_unicode_repair_reanchor_rejects_historical_large_position_before_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        SimpleNamespace(
            thread_id=uuid4(),
            quote_bytes=12,
            position_bytes=1025,
        )
    ]
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "UNICODE_REPAIR_MAX_REANCHOR_POSITION_UTF8_BYTES",
        1024,
    )

    planned = document_text_repair_callbacks._planned_parsed_text_reanchors(
        db=db,
        document_id=uuid4(),
        raw_content="bounded candidate",
        page_offset_map=None,
    )

    assert planned is None
    db.scalars.assert_not_called()
    preflight_sql = str(db.execute.call_args.args[0]).lower()
    assert "octet_length" in preflight_sql
    assert "annotation_threads.quote_text" in preflight_sql
    assert "annotation_threads.position" in preflight_sql
    assert "for update" in preflight_sql


def test_unicode_repair_reanchor_indexes_large_page_map_once() -> None:
    class CountingPageMap(dict[int, list[int]]):
        items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    document_id = uuid4()
    quote_values = [f"unique-quote-{index:03d}" for index in range(256)]
    raw_content = "|".join(quote_values).ljust(4_000, "x")
    threads = [
        SimpleNamespace(
            quote_text=quote,
            position={"kind": "parsed_text", "start_offset": 0, "end_offset": 1},
        )
        for quote in quote_values
    ]
    page_offset_map = CountingPageMap(
        {page + 1: [page * 4, (page + 1) * 4] for page in range(1_000)}
    )
    db = MagicMock()
    db.execute.return_value.all.return_value = _reanchor_preflight(*threads)
    db.scalars.return_value.all.return_value = threads

    planned = document_text_repair_callbacks._planned_parsed_text_reanchors(
        db=db,
        document_id=document_id,
        raw_content=raw_content,
        page_offset_map=page_offset_map,
    )

    assert planned is not None
    assert len(planned) == 256
    assert page_offset_map.items_calls == 1


def test_failed_unicode_repair_keeps_completed_canonical_document(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_content = "readable but damaged \ufffd content"
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="text_only",
        parser_warning_code="unicode_replacement_detected",
    )
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=source_job_id,
        document_id=document_id,
        source_content=source_content,
        source_sha256="c" * 64,
    )
    db = MagicMock()
    db.scalar.return_value = document
    fail = MagicMock(return_value=(durable_job, True))
    monkeypatch.setattr(document_text_repair_callbacks.job_repository, "fail", fail)

    handled = document_text_repair_callbacks.failed_unicode_repair_result(
        db=db,
        durable_job=durable_job,
        result=PDFProcessingResult(
            success=False,
            job_id=str(job_id),
            error="paper_ingestion_parsing_failed",
        ),
        reason="provider leaked a private diagnostic",
        post_commit=(MagicMock(),),
    )

    fail.assert_called_once_with(
        db,
        job_id=job_id,
        error_code="paper_ingestion_parsing_failed",
        result={
            "repair_applied": False,
            "repair_outcome": "worker_failed",
        },
    )
    assert document.processing_status == DocumentProcessingStatus.COMPLETED.value
    assert document.processing_job_id == source_job_id
    assert document.parser_warning_code == "unicode_replacement_detected"
    assert handled.changes == ()
    assert handled.value == {"status": "webhook processed - unicode repair failed"}
    assert len(set(_stub_repair_storage_deletion.call_args.kwargs["object_keys"])) == 2


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("revision", "revision_unsupported"),
        ("job_id", "result_job_id_mismatch"),
        ("markdown", "markdown_artifact_scope_invalid"),
        ("archive", "archive_artifact_scope_invalid"),
    ],
)
def test_unicode_repair_contract_rejects_wrong_revision_identity_and_artifact_scope(
    mutation: str,
    expected: str,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "d" * 64
    source_content = "damaged \ufffd content"
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=source_job_id,
        document_id=document_id,
        source_content=source_content,
        source_sha256=source_sha256,
        repair_revision=(
            "unsupported-v9" if mutation == "revision" else "unicode-replacement-v1"
        ),
    )
    result = _successful_unicode_repair_result(
        job_id=job_id,
        source_sha256=source_sha256,
        raw_content="repaired content",
    )
    if mutation == "job_id":
        result.job_id = str(uuid4())
    elif mutation == "markdown":
        result.parser_markdown_s3_key = "documents/another/canonical.md"
    elif mutation == "archive":
        result.parser_archive_s3_key = "documents/another/mineru-result.zip"

    assert (
        document_text_repair_callbacks.unicode_repair_contract_issue(
            durable_job=durable_job,
            result=result,
        )
        == expected
    )


def test_unicode_repair_contract_rejects_oversized_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    source_sha256 = "3" * 64
    monkeypatch.setattr(
        document_text_repair_callbacks,
        "UNICODE_REPAIR_MAX_CANDIDATE_UTF8_BYTES",
        8,
    )
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=uuid4(),
        document_id=uuid4(),
        source_content="damaged �",
        source_sha256=source_sha256,
    )
    result = _successful_unicode_repair_result(
        job_id=job_id,
        source_sha256=source_sha256,
        raw_content="🧪" * 3,
    )

    assert (
        document_text_repair_callbacks.unicode_repair_contract_issue(
            durable_job=durable_job,
            result=result,
        )
        == "candidate_content_too_large"
    )


def test_invalid_unicode_repair_contract_fails_job_without_callback_retry(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "1" * 64
    source_content = "damaged \ufffd content"
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=source_job_id,
        document_id=document_id,
        source_content=source_content,
        source_sha256=source_sha256,
        repair_revision="unsupported-v9",
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="text_only",
        parser_warning_code="unicode_replacement_detected",
    )
    db = MagicMock()
    db.scalar.return_value = document
    fail = MagicMock(return_value=(durable_job, True))
    monkeypatch.setattr(document_text_repair_callbacks.job_repository, "fail", fail)

    handled = document_text_repair_callbacks.complete_unicode_repair(
        db=db,
        durable_job=durable_job,
        result=_successful_unicode_repair_result(
            job_id=job_id,
            source_sha256=source_sha256,
            raw_content="repaired content",
        ),
        post_commit=(),
    )

    fail.assert_called_once_with(
        db,
        job_id=job_id,
        error_code="pdf_unicode_repair_contract_invalid",
        result={
            "repair_applied": False,
            "repair_outcome": "revision_unsupported",
        },
    )
    assert document.processing_job_id == source_job_id
    assert handled.value["repair_reason"] == "revision_unsupported"
    assert set(_stub_repair_storage_deletion.call_args.kwargs["object_keys"]) == {
        f"documents/{source_sha256}/repairs/unsupported-v9/{job_id}/canonical.md",
        f"documents/{source_sha256}/repairs/unsupported-v9/{job_id}/mineru-result.zip",
    }


def test_invalid_repair_result_uses_persisted_namespace_for_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "2" * 64
    source_content = "damaged � content"
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=source_job_id,
        document_id=document_id,
        source_content=source_content,
        source_sha256=source_sha256,
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="text_only",
        parser_warning_code="unicode_replacement_detected",
    )
    db = MagicMock()
    db.scalar.return_value = document
    monkeypatch.setattr(
        document_text_repair_callbacks.job_repository,
        "fail",
        MagicMock(return_value=(durable_job, True)),
    )
    result = _successful_unicode_repair_result(
        job_id=job_id,
        source_sha256=source_sha256,
        raw_content="repaired content",
    )
    result.job_id = str(uuid4())
    result.parser_markdown_s3_key = "untrusted/foreign-object"

    handled = document_text_repair_callbacks.complete_unicode_repair(
        db=db,
        durable_job=durable_job,
        result=result,
        post_commit=(),
    )

    assert handled.value["repair_reason"] == "result_job_id_mismatch"
    assert set(_stub_repair_storage_deletion.call_args.kwargs["object_keys"]) == {
        f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
        f"{job_id}/canonical.md",
        f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
        f"{job_id}/mineru-result.zip",
    }


@pytest.mark.parametrize(
    ("obsolete_kind", "expected_outcome"),
    [
        ("pointer", "document_generation_changed"),
        ("content", "source_content_changed"),
        ("source", "source_document_changed"),
    ],
)
def test_obsolete_unicode_repair_fails_without_closing_new_source_state(
    monkeypatch: pytest.MonkeyPatch,
    obsolete_kind: str,
    expected_outcome: str,
    _stub_repair_storage_deletion: MagicMock,
) -> None:
    job_id = uuid4()
    source_job_id = uuid4()
    document_id = uuid4()
    source_sha256 = "e" * 64
    original_content = "original damaged \ufffd content"
    current_content = (
        "a concurrent canonical update"
        if obsolete_kind == "content"
        else original_content
    )
    superseding_job_id = uuid4()
    durable_job = _unicode_repair_job(
        job_id=job_id,
        source_job_id=source_job_id,
        document_id=document_id,
        source_content=original_content,
        source_sha256=source_sha256,
    )
    document = SimpleNamespace(
        id=document_id,
        sha256=("f" * 64 if obsolete_kind == "source" else source_sha256),
        s3_object_key=f"documents/{source_sha256}/source.pdf",
        raw_content=current_content,
        processing_job_id=(
            superseding_job_id if obsolete_kind == "pointer" else source_job_id
        ),
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="full",
        parser_warning_code=None,
    )
    db = MagicMock()
    db.scalar.side_effect = [document, document]
    fail = MagicMock(return_value=(durable_job, True))
    counter = MagicMock()
    monkeypatch.setattr(document_text_repair_callbacks.job_repository, "fail", fail)
    monkeypatch.setattr(document_text_repair_callbacks, "add_counter", counter)

    handled = document_text_repair_callbacks.complete_unicode_repair(
        db=db,
        durable_job=durable_job,
        result=_successful_unicode_repair_result(
            job_id=job_id,
            source_sha256=source_sha256,
            raw_content="repaired content",
        ),
        post_commit=(),
    )

    fail.assert_called_once_with(
        db,
        job_id=job_id,
        error_code="pdf_unicode_repair_obsolete",
        result={
            "repair_applied": False,
            "repair_outcome": expected_outcome,
        },
    )
    assert document.raw_content == current_content
    assert document.processing_job_id == (
        superseding_job_id if obsolete_kind == "pointer" else source_job_id
    )
    assert handled.value["repair_reason"] == expected_outcome
    counter.assert_called_once_with(
        "scholens.documents.pdf_unicode_repairs",
        attributes={"outcome": expected_outcome},
    )
    assert len(set(_stub_repair_storage_deletion.call_args.kwargs["object_keys"])) == 2


def test_unicode_repair_invalidates_completed_or_inflight_reflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    reflow_job_id = uuid4()
    artifact = SimpleNamespace(
        job_id=reflow_job_id,
        status="completed",
        error_code=None,
        completed_at=None,
        updated_at=None,
    )
    db = MagicMock()
    db.get.return_value = artifact
    fail = MagicMock(return_value=(SimpleNamespace(), False))
    monkeypatch.setattr(document_text_repair_callbacks.job_repository, "fail", fail)

    changed = document_text_repair_callbacks.invalidate_document_reflow(
        db=db,
        document_id=document_id,
    )

    assert changed is True
    fail.assert_called_once_with(
        db,
        job_id=reflow_job_id,
        error_code="document_reflow_source_revision_changed",
        result={"outcome": "canonical_source_revision_changed"},
    )
    assert artifact.status == "failed"
    assert artifact.error_code == "document_reflow_source_revision_changed"
    assert artifact.completed_at is not None


@pytest.mark.asyncio
async def test_pdf_completion_persists_summary_without_creating_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(id=job_id, created_at=datetime.now(UTC))
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        status=JobStatus.RUNNING.value,
    )
    existing_paper = SimpleNamespace(
        id=document_id,
        title="upload.pdf",
        processing_status=DocumentProcessingStatus.PROCESSING.value,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    completed_paper = SimpleNamespace(
        id=document_id,
        title="Canonical paper title",
        processing_status=DocumentProcessingStatus.COMPLETED.value,
    )
    update_canonical = MagicMock(return_value=completed_paper)

    monkeypatch.setattr(document_job_callbacks, "AdvisoryLock", _AvailableLock)
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=upload_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=durable_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "find_by_upload_job",
        MagicMock(return_value=existing_paper),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    monkeypatch.setattr(
        document_job_callbacks,
        "_complete_pdf_job",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        document_job_callbacks,
        "_enqueue_pdf_postprocess",
        MagicMock(
            return_value=PersistedJob(
                job=SimpleNamespace(id=uuid4()),
                created=False,
            )
        ),
    )
    citation = ResponseCitation(index=1, text="Supporting passage")
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
        metadata=PaperMetadataExtraction(
            title="Canonical paper title",
            summary="The paper's canonical summary.[^1]",
            summary_citations=[citation],
        ),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    callback = PdfProcessingWebhookData(
        task_id=str(job_id),
        status="completed",
        result=result,
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )
    db = MagicMock()

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        callback,
        db,
        actor=actor,
        operation=operation,
    )

    update = update_canonical.call_args.kwargs["update"]
    assert update.summary == result.metadata.summary
    assert update.summary_citations == [citation]
    assert handled.value == {
        "status": "webhook processed",
        "document_id": str(document_id),
    }
    assert all(
        not str(change.action).startswith("conversation.") for change in handled.changes
    )


@pytest.mark.asyncio
async def test_terminal_pdf_callback_does_not_rewrite_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    actor = _actor()
    update_canonical = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=SimpleNamespace(id=job_id)),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(
            return_value=SimpleNamespace(
                operation=JobOperation.PDF_PROCESS.value,
                requested_by_id=actor.id,
                status=JobStatus.COMPLETED.value,
            )
        ),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        metadata=PaperMetadataExtraction(title="Paper"),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )
    db = MagicMock()

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        PdfProcessingWebhookData(
            task_id=str(job_id),
            status="completed",
            result=result,
        ),
        db,
        actor=actor,
        operation=operation,
    )

    assert handled.value == {"status": "webhook ignored - job is terminal"}
    update_canonical.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.FAILED.value, JobStatus.CANCELLED.value])
async def test_terminal_repair_callback_cleans_late_worker_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    _stub_repair_storage_deletion: MagicMock,
    status: str,
) -> None:
    job_id = uuid4()
    actor = _actor()
    origin_operation_id = uuid4()
    correlation_id = uuid4()
    source_sha256 = "a" * 64
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=SimpleNamespace(id=job_id)),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(
            return_value=SimpleNamespace(
                id=job_id,
                operation=JobOperation.PDF_PROCESS.value,
                requested_by_id=actor.id,
                status=status,
                payload={
                    "repair_kind": "unicode_replacement",
                    "repair_revision": "unicode-replacement-v1",
                    "content_sha256": source_sha256,
                },
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
        ),
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="late candidate",
        page_offset_map={1: [0, 14]},
        parser_markdown_s3_key=(
            f"documents/{source_sha256}/repairs/unicode-replacement-v1/"
            f"{job_id}/canonical.md"
        ),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )
    db = MagicMock()

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        PdfProcessingWebhookData(
            task_id=str(job_id),
            status="completed",
            result=result,
        ),
        db,
        actor=actor,
        operation=operation,
    )

    assert handled.value == {"status": "webhook ignored - job is terminal"}
    prefix = f"documents/{source_sha256}/repairs/unicode-replacement-v1/{job_id}/"
    _stub_repair_storage_deletion.assert_called_once_with(
        db,
        object_keys=(f"{prefix}canonical.md", f"{prefix}mineru-result.zip"),
        idempotency_key=f"unicode-repair:{job_id}:terminal-{status}",
        origin_operation_id=origin_operation_id,
        correlation_id=correlation_id,
    )


@pytest.mark.asyncio
async def test_pdf_completion_rejects_mismatched_object_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(id=job_id, created_at=datetime.now(UTC))
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        status=JobStatus.RUNNING.value,
    )
    existing_paper = SimpleNamespace(
        id=document_id,
        title="upload.pdf",
        processing_status=DocumentProcessingStatus.PROCESSING.value,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    update_canonical = MagicMock()
    fail_job = MagicMock()

    monkeypatch.setattr(document_job_callbacks, "AdvisoryLock", _AvailableLock)
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=upload_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=durable_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        fail_job,
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "find_by_upload_job",
        MagicMock(return_value=existing_paper),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        s3_object_key=f"documents/{'b' * 64}/source.pdf",
        metadata=PaperMetadataExtraction(title="Canonical paper title"),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        PdfProcessingWebhookData(
            task_id=str(job_id),
            status="completed",
            result=result,
        ),
        MagicMock(),
        actor=actor,
        operation=operation,
    )

    update_canonical.assert_not_called()
    assert fail_job.call_args.kwargs["error_code"] == "job_result_key_mismatch"
    assert handled.value == {
        "status": "webhook processed - failed due to object key mismatch"
    }


def test_failed_upload_compensates_only_memberships_this_job_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    project_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(
        id=job_id,
        reference_created=False,
        reference_created_library=True,
        reference_created_project=True,
    )
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        project_id=project_id,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
        progress_code="parsing",
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.PROCESSING.value,
    )
    db = MagicMock()
    db.scalar.return_value = document

    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=SimpleNamespace(job=durable_job, **vars(upload_job))),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        MagicMock(),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    gc_schedule = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks,
        "schedule_document_gc",
        gc_schedule,
    )

    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    changes = document_job_callbacks.handle_failed_upload(
        db,
        str(job_id),
        actor,
        operation=operation,
        reason="pdf_content_insufficient",
    )

    assert any(str(change.action) == "document.processing_failed" for change in changes)
    delete_calls = [call.args[0] for call in db.execute.call_args_list]
    assert len(delete_calls) == 2
    gc_schedule.assert_called_once_with(
        db,
        document_id=document_id,
        origin_operation_id=operation.trace.operation_id,
        correlation_id=operation.trace.correlation_id,
    )


def test_failed_upload_keeps_pre_existing_memberships_when_nothing_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(
        id=job_id,
        reference_created=False,
        reference_created_library=False,
        reference_created_project=False,
    )
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        project_id=None,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
        progress_code="parsing",
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.PROCESSING.value,
    )
    db = MagicMock()
    db.scalar.return_value = document

    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=SimpleNamespace(job=durable_job, **vars(upload_job))),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        MagicMock(),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    gc_schedule = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks,
        "schedule_document_gc",
        gc_schedule,
    )

    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    document_job_callbacks.handle_failed_upload(
        db,
        str(job_id),
        actor,
        operation=operation,
        reason="pdf_content_insufficient",
    )

    assert db.execute.call_args_list == []
    gc_schedule.assert_not_called()


def test_apply_pdf_postprocess_drops_invalid_fields_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed provider publish_date must not fail the whole callback."""
    paper = SimpleNamespace(
        id=uuid4(),
        raw_content="content",
        doi=None,
        journal=None,
        publisher=None,
        publish_date=None,
        field_provenance=None,
    )
    db = MagicMock()
    updated_paper = SimpleNamespace(
        id=paper.id,
        raw_content="content",
        doi="10.1000/example",
        journal=None,
        publisher=None,
        publish_date=None,
        field_provenance=None,
    )
    update_canonical = MagicMock(return_value=updated_paper)
    monkeypatch.setattr(
        document_job_callbacks.document_search_repository,
        "replace_passage_index",
        MagicMock(),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )

    result = document_job_callbacks._apply_pdf_postprocess(
        db=db,
        paper=paper,
        actor=_actor(),
        resolution=PdfPostprocessResolution(
            doi="10.1000/example",
            publish_date="not-a-date",
        ),
    )

    assert result is True
    assert update_canonical.call_count == 1
    applied = update_canonical.call_args.kwargs["update"]
    assert isinstance(applied, DocumentUpdate)
    assert applied.doi == "10.1000/example"
    assert applied.publish_date is None
