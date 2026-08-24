"""Bounded, namespace-safe generated-object deletion scheduling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from scholens_job_contracts import (
    MAX_STORAGE_DELETE_BATCH_JSON_BYTES,
    MAX_STORAGE_DELETE_KEYS_PER_BATCH,
    require_storage_delete_batch,
    storage_delete_batch_digest,
    storage_delete_batch_json_bytes,
)
from sqlalchemy.orm import Session

from app.bootstrap.adapters import document_job_callbacks, storage_cleanup
from app.modules.jobs.application.contracts import StorageDeleteCallback
from app.shared.domain import AppError
from app.shared.domain.enums import JobOperation


def _document_key(index: int, *, suffix: str = "canonical.md") -> str:
    return f"documents/{index:064x}/{suffix}"


def _schedule(
    monkeypatch: pytest.MonkeyPatch,
    *,
    object_keys: list[str],
    created: tuple[bool, ...] | None = None,
) -> tuple[storage_cleanup.ScheduledStorageDeletion, MagicMock]:
    enqueue = MagicMock()
    created_values = iter(created or (True,) * len(object_keys))

    def persist(_db: Session, *, request: object) -> object:
        return SimpleNamespace(
            job=SimpleNamespace(id=request.job_id),
            created=next(created_values),
        )

    enqueue.side_effect = persist
    monkeypatch.setattr(storage_cleanup.job_repository, "enqueue", enqueue)
    monkeypatch.setattr(
        storage_cleanup,
        "get_webhook_base_url",
        lambda: "https://server.internal",
    )
    result = storage_cleanup.schedule_storage_deletion(
        MagicMock(spec=Session),
        object_keys=object_keys,
        idempotency_key="project:00000000-0000-4000-8000-000000000001",
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )
    assert result is not None
    return result, enqueue


def test_storage_cleanup_splits_deterministic_batches_and_reports_exact_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = [
        _document_key(index)
        for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH * 2 + 5)
    ]

    result, enqueue = _schedule(
        monkeypatch,
        object_keys=keys,
        created=(True, False, True),
    )

    assert result.object_count == len(keys)
    assert result.job_count == 3
    assert result.created_job_count == 2
    requests = [call.kwargs["request"] for call in enqueue.call_args_list]
    assert [request.payload["object_count"] for request in requests] == [100, 100, 5]
    assert [request.payload["batch_index"] for request in requests] == [0, 1, 2]
    assert all(
        len(storage_delete_batch_json_bytes(request.task_kwargs["object_keys"]))
        <= MAX_STORAGE_DELETE_BATCH_JSON_BYTES
        for request in requests
    )
    for index, request in enumerate(requests):
        batch = require_storage_delete_batch(request.task_kwargs["object_keys"])
        digest = storage_delete_batch_digest(batch)
        assert request.payload["object_keys_digest"] == digest
        assert request.idempotency_key.endswith(f"batch:{index:06d}:{digest}")
        assert str(request.job_id) in request.task_kwargs["callback_url"]
        assert str(request.job_id) in request.task_kwargs["claim_url"]


def test_storage_cleanup_idempotency_is_stable_for_same_ordered_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = [_document_key(index) for index in range(105)]
    first, first_enqueue = _schedule(monkeypatch, object_keys=keys)
    first_keys = [
        call.kwargs["request"].idempotency_key for call in first_enqueue.call_args_list
    ]

    second, second_enqueue = _schedule(monkeypatch, object_keys=list(keys))
    second_keys = [
        call.kwargs["request"].idempotency_key for call in second_enqueue.call_args_list
    ]

    assert first.object_count == second.object_count == len(keys)
    assert first_keys == second_keys


def test_created_cleanup_job_ids_are_re_read_in_bounded_keyset_pages() -> None:
    job_ids = tuple(UUID(int=index + 1) for index in range(205))
    db = MagicMock(spec=Session)

    def page(values: tuple[UUID, ...]) -> MagicMock:
        result = MagicMock()
        result.all.return_value = values
        return result

    db.scalars.side_effect = [
        page(job_ids[:100]),
        page(job_ids[100:200]),
        page(job_ids[200:]),
        page(()),
    ]

    observed = tuple(
        storage_cleanup.iter_created_cleanup_job_ids(
            db,
            origin_operation_id=uuid4(),
            operations=(JobOperation.DOCUMENT_GC, JobOperation.STORAGE_DELETE),
        )
    )

    assert observed == job_ids
    assert db.scalars.call_count == 4
    assert all("LIMIT" in str(call.args[0]) for call in db.scalars.call_args_list)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "uploads/1/private/source.pdf",
        "documents/../private.pdf",
        "documents/evil\x00path.pdf",
        "documents/论文.pdf",
    ],
)
def test_storage_cleanup_rejects_hostile_key_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    enqueue = MagicMock()
    monkeypatch.setattr(storage_cleanup.job_repository, "enqueue", enqueue)

    with pytest.raises(ValueError, match="storage_delete"):
        storage_cleanup.schedule_storage_deletion(
            MagicMock(spec=Session),
            object_keys=[key],
            idempotency_key="document:00000000-0000-4000-8000-000000000001",
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
        )

    enqueue.assert_not_called()


def test_storage_delete_completion_rejects_an_inaccurate_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    job = SimpleNamespace(
        operation=JobOperation.STORAGE_DELETE.value,
        payload={"object_keys": [_document_key(1), _document_key(2)]},
    )
    complete = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=job),
    )
    monkeypatch.setattr(document_job_callbacks.job_repository, "complete", complete)

    with pytest.raises(AppError) as error:
        document_job_callbacks.complete_storage_delete_job(
            job_id,
            StorageDeleteCallback(task_id=job_id, deleted_count=1),
            MagicMock(spec=Session),
        )

    assert error.value.code == "storage_delete_receipt_mismatch"
    complete.assert_not_called()


def test_storage_delete_completion_records_the_exact_batch_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    job = SimpleNamespace(
        operation=JobOperation.STORAGE_DELETE.value,
        payload={"object_keys": [_document_key(1), _document_key(2)]},
    )
    complete = MagicMock(return_value=(job, True))
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=job),
    )
    monkeypatch.setattr(document_job_callbacks.job_repository, "complete", complete)

    document_job_callbacks.complete_storage_delete_job(
        job_id,
        StorageDeleteCallback(task_id=job_id, deleted_count=2),
        MagicMock(spec=Session),
    )

    assert complete.call_args.kwargs["result"] == {"deleted_count": 2}
