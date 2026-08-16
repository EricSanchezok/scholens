import json
from unittest.mock import MagicMock, patch

import pytest

from src.zotero import (
    ZoteroClient,
    ZoteroJobCredential,
    ZoteroJobError,
    _annotations_json,
    _bounded_version_batch,
    import_items,
    sync_items,
)


def _credential() -> ZoteroJobCredential:
    return ZoteroJobCredential(
        user_id="42",
        api_key="private-zotero-api-key",
        revision="revision-1",
    )


def _item(key: str, version: int) -> dict[str, object]:
    return {
        "key": key,
        "version": version,
        "data": {"itemType": "journalArticle", "title": key},
    }


def test_zotero_credential_secret_is_not_in_repr() -> None:
    credential = _credential()

    assert "private-zotero-api-key" not in repr(credential)
    assert "revision-1" in repr(credential)


def test_annotation_snapshot_keeps_only_stable_remote_keys() -> None:
    serialized = _annotations_json(
        [
            {"key": "ANN1", "data": {"annotationText": "hello"}},
            {"key": "", "data": {"annotationText": "skip"}},
        ]
    )

    assert json.loads(serialized) == [
        {"key": "ANN1", "data": {"annotationText": "hello"}}
    ]


def test_import_stops_before_provider_io_after_cancellation() -> None:
    with patch.object(ZoteroClient, "items") as items:
        with pytest.raises(ZoteroJobError) as raised:
            import_items(
                task_id="job-1",
                credential=_credential(),
                item_keys=["ITEM1"],
                is_active=lambda: False,
            )

    assert raised.value.code == "zotero_operation_cancelled"
    items.assert_not_called()


def test_version_batch_never_splits_items_with_same_version() -> None:
    values = [_item(f"ITEM{index}", index) for index in range(1, 50)]
    values.extend([_item("ITEM50", 50), _item("ITEM51", 50), _item("ITEM52", 51)])

    selected = _bounded_version_batch(values)

    assert [value["key"] for value in selected[-2:]] == ["ITEM50", "ITEM51"]
    assert len(selected) == 51


def test_sync_advances_only_to_processed_incremental_version() -> None:
    changed = [_item(f"ITEM{index}", index) for index in range(1, 52)]
    client = MagicMock()
    client.items_since.return_value = (changed, 80)
    client.current_library_version.return_value = 80
    with (
        patch("src.zotero.ZoteroClient", return_value=client),
        patch(
            "src.zotero._prepare_import_item",
            side_effect=lambda **kwargs: {
                "item_key": kwargs["item_key"],
                "status": "failed",
                "error_code": "zotero_pdf_unavailable",
            },
        ),
    ):
        result = sync_items(
            task_id="job-1",
            credential=_credential(),
            targets=[],
            auto_import_version=0,
            is_active=lambda: True,
        )

    assert result["library_version"] == 50
    assert len(result["auto_imports"]) == 50


def test_rate_limit_exhaustion_uses_stable_error_code() -> None:
    response = MagicMock(status_code=429)
    response.headers = {"Retry-After": "invalid"}
    client = ZoteroClient(_credential())

    with (
        patch.object(client._session, "get", return_value=response),
        patch("src.zotero.time.sleep"),
    ):
        with pytest.raises(ZoteroJobError) as raised:
            client.current_library_version()

    assert raised.value.code == "zotero_rate_limited"
