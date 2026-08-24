"""Reference-safe canonical document collection behavior."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.bootstrap.adapters.document_gc import (
    _repair_storage_keys,
    collect_document_if_due,
)
from app.bootstrap.adapters.storage_cleanup import (
    ScheduledStorageDeletion,
)
from app.database.models import Document
from app.shared.domain import AppError


def _document(*, gc_after: datetime) -> Document:
    digest = "a" * 64
    return Document(
        id=uuid4(),
        sha256=digest,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{digest}/source.pdf",
        preview_s3_key=f"documents/{digest}/preview.webp",
        gc_after=gc_after,
    )


def _scheduled_storage_deletion(*, object_count: int = 2) -> ScheduledStorageDeletion:
    return ScheduledStorageDeletion(
        job_count=1,
        created_job_count=1,
        object_count=object_count,
    )


def test_document_gc_is_cancelled_when_a_reference_reappears() -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, True]
    operation_id = uuid4()
    correlation_id = uuid4()

    result = collect_document_if_due(
        db,
        document_id=document.id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
        now=now,
    )

    assert result.cancelled is True
    assert result.deleted is False
    assert document.gc_after is None
    db.delete.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_document_gc_schedules_storage_delete_in_the_same_uow(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    empty_rows = MagicMock(all=MagicMock(return_value=[]))
    empty_rows.__iter__.return_value = iter(())
    db.scalar.side_effect = [document, False, 0, 0, None]
    db.scalars.side_effect = [empty_rows, empty_rows, empty_rows]
    db.execute.side_effect = [[], MagicMock()]
    operation_id = uuid4()
    correlation_id = uuid4()
    captured_keys: tuple[str, ...] = ()

    def schedule_storage(_db: Session, **kwargs: object) -> ScheduledStorageDeletion:
        nonlocal captured_keys
        captured_keys = tuple(kwargs["object_keys"])  # type: ignore[arg-type]
        return _scheduled_storage_deletion()

    scheduled = MagicMock(side_effect=schedule_storage)
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_storage_deletion",
        scheduled,
    )

    result = collect_document_if_due(
        db,
        document_id=document.id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
        now=now,
    )

    assert result.deleted is True
    assert result.storage_deletion == _scheduled_storage_deletion()
    scheduled.assert_called_once()
    call = scheduled.call_args
    assert set(captured_keys) == {
        document.s3_object_key,
        document.preview_s3_key,
    }
    assert call.kwargs["origin_operation_id"] == operation_id
    assert call.kwargs["correlation_id"] == correlation_id
    db.delete.assert_called_once_with(document)
    db.flush.assert_called_once()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_document_gc_deletes_repair_namespace_and_sanitizes_legacy_result(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    repair_job_id = uuid4()
    repair_job = SimpleNamespace(
        id=repair_job_id,
        payload={
            "repair_kind": "unicode_replacement",
            "repair_revision": "unicode-replacement-v1",
            "content_sha256": document.sha256,
        },
        result={
            "success": True,
            "repair_applied": False,
            "raw_content": "private candidate body" * 10_000,
            "page_offset_map": {"1": [0, 10]},
        },
    )
    repair_canonical_key = (
        f"documents/{document.sha256}/repairs/unicode-replacement-v1/"
        f"{repair_job_id}/canonical.md"
    )
    document.parser_markdown_s3_key = repair_canonical_key
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, False, 0, 1, repair_job, None]

    def _rows(values):
        rows = MagicMock()
        rows.all.return_value = values
        rows.__iter__.return_value = iter(values)
        return rows

    db.scalars.side_effect = [_rows([repair_job_id]), _rows([]), _rows([])]
    db.execute.side_effect = [
        [
            (
                repair_job_id,
                document.sha256,
                "unicode-replacement-v1",
            )
        ],
        [],
        MagicMock(),
    ]
    captured_keys: tuple[str, ...] = ()

    def schedule_storage(_db: Session, **kwargs: object) -> ScheduledStorageDeletion:
        nonlocal captured_keys
        captured_keys = tuple(kwargs["object_keys"])  # type: ignore[arg-type]
        return _scheduled_storage_deletion(object_count=4)

    scheduled = MagicMock(side_effect=schedule_storage)
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_storage_deletion",
        scheduled,
    )

    result = collect_document_if_due(
        db,
        document_id=document.id,
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
        now=now,
    )

    assert result.deleted is True
    assert set(captured_keys) >= {
        repair_canonical_key,
        f"documents/{document.sha256}/repairs/unicode-replacement-v1/"
        f"{repair_job_id}/mineru-result.zip",
    }
    assert captured_keys == tuple(sorted(set(captured_keys)))
    assert len(captured_keys) == 4
    assert repair_job.result == {
        "success": True,
        "repair_applied": False,
        "repair_outcome": "legacy_result_sanitized",
    }


def test_document_gc_never_derives_repair_keys_from_another_document_digest() -> None:
    document = _document(gc_after=datetime.now(timezone.utc))
    db = MagicMock(spec=Session)
    db.execute.return_value = [
        (uuid4(), "b" * 64, "unicode-replacement-v1"),
    ]

    with pytest.raises(RuntimeError, match="repair_scope_mismatch"):
        tuple(
            _repair_storage_keys(
                db,
                document_id=document.id,
                content_sha256=document.sha256,
            )
        )


def test_document_gc_retries_instead_of_waiting_on_a_locked_repair_job(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    locked_rows = MagicMock()
    locked_rows.__iter__.return_value = iter(())
    db.scalar.side_effect = [document, False, 0, 1]
    db.scalars.return_value = locked_rows
    scheduled = MagicMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_storage_deletion",
        scheduled,
    )

    with pytest.raises(AppError) as error:
        collect_document_if_due(
            db,
            document_id=document.id,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            now=now,
        )

    assert error.value.code == "document_gc_repair_busy"
    scheduled.assert_not_called()
    db.delete.assert_not_called()


def test_document_gc_retries_while_document_processing_is_active(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, False, 1]
    scheduled = MagicMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_storage_deletion",
        scheduled,
    )

    with pytest.raises(AppError) as error:
        collect_document_if_due(
            db,
            document_id=document.id,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            now=now,
        )

    assert error.value.code == "document_gc_has_active_jobs"
    db.scalars.assert_not_called()
    scheduled.assert_not_called()
    db.delete.assert_not_called()
