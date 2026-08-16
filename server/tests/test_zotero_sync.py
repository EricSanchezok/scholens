"""Focused Zotero annotation and synchronization tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.bootstrap.adapters import zotero_gateway as gateway_module
from app.bootstrap.adapters.zotero_annotations import (
    _page_number,
    apply_annotation_snapshot,
)
from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.modules.integrations.zotero.application.zotero import (
    ZoteroSyncBatch,
    ZoteroSyncFailure,
    ZoteroSyncTarget,
    ZoteroSyncUpdate,
)
from app.shared.application import Actor
from app.shared.domain.enums import ZoteroAnnotationSyncStatus
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def test_page_number_prefers_pdf_page_index_over_printed_label() -> None:
    assert (
        _page_number(
            {
                "annotationPageLabel": "583",
                "annotationPosition": json.dumps(
                    {"pageIndex": 0, "rects": [[0, 0, 1, 1]]}
                ),
            }
        )
        == 1
    )


def test_apply_annotation_snapshot_is_idempotent_by_zotero_key() -> None:
    db = MagicMock()
    actor = _actor()
    document_id = uuid4()
    raw_file = SimpleNamespace(
        raw_content="hello world",
        page_offsets={1: (0, 11)},
    )
    annotation = {
        "key": "ANN1",
        "data": {
            "annotationType": "highlight",
            "annotationText": "hello",
            "annotationPosition": json.dumps(
                {"pageIndex": 0, "rects": [[0, 0, 10, 10]]}
            ),
        },
    }

    with (
        patch(
            "app.bootstrap.adapters.zotero_annotations.require_parsed_content",
            return_value=raw_file,
        ),
        patch.object(
            gateway_module,
            "apply_annotation_snapshot",
            wraps=apply_annotation_snapshot,
        ),
        patch(
            "app.bootstrap.adapters.zotero_annotations.research_repository"
        ) as repository,
    ):
        repository.get_zotero_annotation_keys.return_value = {"ANN1"}
        assert (
            apply_annotation_snapshot(
                db,
                document_id=document_id,
                user=actor,
                annotations_payload=[annotation],
                page_dimensions=((0, 612.0, 792.0),),
            )
            == 0
        )
        repository.create_annotation_thread.assert_not_called()


def test_apply_sync_with_empty_annotations_does_not_require_paper_content() -> None:
    db = MagicMock()
    actor = _actor()
    document_id = uuid4()
    imported_item_id = uuid4()
    imported_item = SimpleNamespace(
        id=imported_item_id,
        document_id=document_id,
    )
    target = ZoteroSyncTarget(
        imported_item_id=imported_item_id,
        item_key="ITEM",
        document_id=document_id,
        attachment_key="ATTACHMENT",
        document_source_key="documents/source.pdf",
    )
    batch = ZoteroSyncBatch(
        updates=(
            ZoteroSyncUpdate(
                target=target,
                annotations_json="[]",
                page_dimensions=(),
            ),
        ),
        failures=(),
    )

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=imported_item,
        ),
        patch.object(
            gateway_module.zotero_import_repository,
            "update_after_sync",
        ),
        patch.object(
            gateway_module.document_repository,
            "find_accessible",
            return_value=SimpleNamespace(id=document_id),
        ),
        patch.object(gateway_module, "apply_annotation_snapshot") as apply,
    ):
        mutation = DefaultZoteroGateway(db, connections=MagicMock()).apply_sync(
            actor=actor,
            batch=batch,
            credential_revision=uuid4(),
        )

    assert mutation.response.synced_papers_count == 1
    assert mutation.response.new_annotations_count == 0
    assert mutation.changed_document_ids == ()
    apply.assert_not_called()


def test_syncable_repository_excludes_url_imports() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    zotero_import_repository.list_syncable_by_user(db, user_id=7, limit=10)

    statement = db.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "zotero_imported_items.import_source = 'pdf_attachment'" in compiled
    assert "zotero_imported_items.zotero_attachment_key IS NOT NULL" in compiled
    assert "zotero_imported_items.annotation_sync_status = 'active'" in compiled
    assert "last_sync_attempted_at ASC NULLS FIRST" in compiled


def test_failed_front_page_advances_attempt_order_without_faking_success() -> None:
    attempted_at = datetime.now(UTC)
    db = MagicMock()
    failed_front_page = [
        SimpleNamespace(
            last_sync_attempted_at=None,
            last_synced_at=None,
            annotation_sync_status=ZoteroAnnotationSyncStatus.ACTIVE.value,
            last_sync_error_code=None,
        )
        for _ in range(500)
    ]
    unseen = SimpleNamespace(
        last_sync_attempted_at=None,
        last_synced_at=None,
        annotation_sync_status=ZoteroAnnotationSyncStatus.ACTIVE.value,
        last_sync_error_code=None,
    )

    for item in failed_front_page:
        zotero_import_repository.update_after_sync_failure(
            db,
            item=item,
            error_code="zotero_rate_limited",
            attempted_at=attempted_at,
            source_unavailable=False,
        )

    next_window = sorted(
        [*failed_front_page, unseen],
        key=lambda item: (
            item.last_sync_attempted_at is not None,
            item.last_sync_attempted_at or datetime.min.replace(tzinfo=UTC),
        ),
    )[:500]
    assert unseen in next_window
    assert unseen is next_window[0]
    assert all(item.last_synced_at is None for item in failed_front_page)


def test_permanent_missing_attachment_disables_only_future_annotation_sync() -> None:
    item = SimpleNamespace(
        last_sync_attempted_at=None,
        last_synced_at=None,
        annotation_sync_status=ZoteroAnnotationSyncStatus.ACTIVE.value,
        last_sync_error_code=None,
    )

    zotero_import_repository.update_after_sync_failure(
        MagicMock(),
        item=item,
        error_code="zotero_attachment_not_found",
        attempted_at=datetime.now(UTC),
        source_unavailable=True,
    )

    assert item.annotation_sync_status == "source_unavailable"
    assert item.last_sync_error_code == "zotero_attachment_not_found"
    assert item.last_synced_at is None


def test_apply_sync_consumes_provider_failures_as_attempts() -> None:
    db = MagicMock()
    imported_item = SimpleNamespace(id=uuid4())
    failures = tuple(
        ZoteroSyncFailure(
            item_key=f"F{index:07d}",
            error_code=(
                "zotero_attachment_not_found" if index == 0 else "zotero_rate_limited"
            ),
        )
        for index in range(500)
    )
    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=imported_item,
        ),
        patch.object(
            gateway_module.zotero_import_repository,
            "update_after_sync_failure",
        ) as update_failure,
    ):
        mutation = DefaultZoteroGateway(db, connections=MagicMock()).apply_sync(
            actor=_actor(),
            batch=ZoteroSyncBatch(updates=(), failures=failures),
            credential_revision=uuid4(),
        )

    assert mutation.response.synced_papers_count == 0
    assert update_failure.call_count == 500
    assert update_failure.call_args_list[0].kwargs["source_unavailable"] is True
    assert update_failure.call_args_list[1].kwargs["source_unavailable"] is False


def test_apply_sync_does_not_advance_targets_omitted_by_worker_budget() -> None:
    scheduled_keys = [f"I{index:07d}" for index in range(500)]
    returned_keys = scheduled_keys[:4]
    imported_by_key = {
        item_key: SimpleNamespace(id=uuid4(), zotero_item_key=item_key)
        for item_key in returned_keys
    }
    callback = ZoteroSyncBatch(
        updates=(),
        failures=tuple(
            ZoteroSyncFailure(
                item_key=item_key,
                error_code="zotero_rate_limited",
            )
            for item_key in returned_keys
        ),
    )

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            side_effect=lambda _db, *, user_id, zotero_item_key: imported_by_key[
                zotero_item_key
            ],
        ) as get_item,
        patch.object(
            gateway_module.zotero_import_repository,
            "update_after_sync_failure",
        ) as update_failure,
    ):
        DefaultZoteroGateway(MagicMock(), connections=MagicMock()).apply_sync(
            actor=_actor(),
            batch=callback,
            credential_revision=uuid4(),
        )

    assert get_item.call_count == len(returned_keys)
    assert update_failure.call_count == len(returned_keys)
    assert {
        call.kwargs["item"].zotero_item_key for call in update_failure.call_args_list
    } == set(returned_keys)
    assert set(scheduled_keys[len(returned_keys) :]).isdisjoint(returned_keys)
