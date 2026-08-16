import json
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from scholens_job_contracts import ZOTERO_CALLBACK_HTTP_TIMEOUT_SECONDS

from src.tasks import import_zotero_items_task
from src.zotero import (
    ZoteroClient,
    ZoteroJobCredential,
    ZoteroJobError,
    _annotations_json,
    _bounded_version_batch,
    _fetch_public_pdf,
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
            {"key": "ANNOT001", "data": {"annotationText": "hello"}},
            {"key": "", "data": {"annotationText": "skip"}},
        ]
    )

    assert json.loads(serialized) == [
        {"key": "ANNOT001", "data": {"annotationText": "hello"}}
    ]


def test_import_stops_before_provider_io_after_cancellation() -> None:
    with patch.object(ZoteroClient, "items") as items:
        with pytest.raises(ZoteroJobError) as raised:
            import_items(
                task_id="job-1",
                credential=_credential(),
                item_keys=["ITEM0001"],
                is_active=lambda: False,
            )

    assert raised.value.code == "zotero_operation_cancelled"
    items.assert_not_called()


@pytest.mark.parametrize("item_key", ["../ITEM1", "item0001", "ITEM/001"])
def test_worker_rejects_path_shaped_zotero_keys_before_provider_io(
    item_key: str,
) -> None:
    with patch.object(ZoteroClient, "items") as items:
        with pytest.raises(ZoteroJobError) as raised:
            import_items(
                task_id="job-1",
                credential=_credential(),
                item_keys=[item_key],
            )

    assert raised.value.code == "zotero_request_invalid"
    items.assert_not_called()


def test_import_deletes_prior_staging_objects_after_late_credential_failure() -> None:
    client = MagicMock()
    client.items.return_value = [_item("ITEM0001", 1), _item("ITEM0002", 2)]

    def prepare(**kwargs):  # type: ignore[no-untyped-def]
        if kwargs["item_key"] == "ITEM0001":
            key = "zotero-imports/job-1/ITEM0001.pdf"
            kwargs["uploaded_keys"].append(key)
            return {
                "item_key": "ITEM0001",
                "status": "ready",
                "s3_object_key": key,
            }
        raise ZoteroJobError(
            "zotero_credentials_invalid",
            invalid_credential=True,
        )

    with (
        patch("src.zotero.ZoteroClient", return_value=client),
        patch("src.zotero._prepare_import_item", side_effect=prepare),
        patch("src.zotero.s3_service.delete_file") as delete_file,
    ):
        with pytest.raises(ZoteroJobError) as raised:
            import_items(
                task_id="job-1",
                credential=_credential(),
                item_keys=["ITEM0001", "ITEM0002"],
                is_active=lambda: True,
            )

    assert raised.value.code == "zotero_credentials_invalid"
    delete_file.assert_called_once_with("zotero-imports/job-1/ITEM0001.pdf")


def test_import_deletes_staging_objects_after_cooperative_cancellation() -> None:
    client = MagicMock()
    client.items.return_value = [_item("ITEM0001", 1), _item("ITEM0002", 2)]
    activity = iter([True, True, False])

    def prepare(**kwargs):  # type: ignore[no-untyped-def]
        key = "zotero-imports/job-1/ITEM0001.pdf"
        kwargs["uploaded_keys"].append(key)
        return {
            "item_key": "ITEM0001",
            "status": "ready",
            "s3_object_key": key,
        }

    with (
        patch("src.zotero.ZoteroClient", return_value=client),
        patch("src.zotero._prepare_import_item", side_effect=prepare),
        patch("src.zotero.s3_service.delete_file") as delete_file,
    ):
        with pytest.raises(ZoteroJobError) as raised:
            import_items(
                task_id="job-1",
                credential=_credential(),
                item_keys=["ITEM0001", "ITEM0002"],
                is_active=lambda: next(activity),
            )

    assert raised.value.code == "zotero_operation_cancelled"
    delete_file.assert_called_once_with("zotero-imports/job-1/ITEM0001.pdf")


def test_callback_timeout_keeps_staging_for_server_or_lifecycle_cleanup() -> None:
    task_id = "10000000-0000-4000-8000-000000000001"
    staged_key = f"zotero-imports/{task_id}/ITEM0001.pdf"
    prepared = [
        {
            "item_key": "ITEM0001",
            "status": "ready",
            "s3_object_key": staged_key,
        }
    ]

    with (
        patch("src.tasks._claim_job", return_value=True),
        patch("src.tasks._zotero_progress", return_value=True),
        patch("src.tasks._fetch_zotero_credential", return_value=_credential()),
        patch("src.tasks.import_zotero_items", return_value=(prepared, 10)),
        patch(
            "src.tasks.post_signed_json",
            side_effect=requests.Timeout("callback result unknown"),
        ) as post,
        patch("src.zotero.s3_service.delete_file") as delete_file,
    ):
        with pytest.raises(RuntimeError, match="zotero_import_callback_failed"):
            import_zotero_items_task.apply(
                args=(
                    {"item_keys": ["ITEM0001"], "credential_revision": "revision-1"},
                    "https://server.example/callback",
                    "https://server.example/claim",
                    "https://server.example/credential",
                    "https://server.example/progress",
                ),
                task_id=task_id,
                throw=True,
            ).get()

    assert post.call_args.kwargs["timeout"] == ZOTERO_CALLBACK_HTTP_TIMEOUT_SECONDS
    delete_file.assert_not_called()


def test_version_batch_stays_bounded_when_more_than_fifty_share_a_version() -> None:
    values = [_item(f"ITEM{index:04}", 50) for index in range(75)]

    selected = _bounded_version_batch(values)

    assert len(selected) == 50
    assert selected[-1]["key"] == "ITEM0049"


def test_incremental_fetch_is_one_bounded_provider_page() -> None:
    response = MagicMock(status_code=200)
    response.headers = {
        "Last-Modified-Version": "80",
        "Total-Results": "75",
    }
    response.json.return_value = [_item(f"ITEM{index:04}", 50) for index in range(50)]
    client = ZoteroClient(_credential())

    with patch.object(client, "_request", return_value=response) as request:
        items, version, has_more = client.items_since(40, start=0, limit=50)

    assert len(items) == 50
    assert version == 80
    assert has_more is True
    assert request.call_args.kwargs["params"] == {
        "since": 40,
        "limit": 50,
        "start": 0,
        "sort": "dateModified",
        "direction": "asc",
        "itemType": "conferencePaper || journalArticle || preprint",
    }
    response.close.assert_called_once_with()


def test_sync_uses_secondary_cursor_for_more_than_fifty_items_at_one_version() -> None:
    changed = [_item(f"ITEM{index:04}", 50) for index in range(75)]
    client = MagicMock()
    client.items_since.return_value = (changed[:50], 80, True)
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
            auto_import_start=0,
            is_active=lambda: True,
        )

    assert result["library_version"] == 80
    assert len(result["auto_imports"]) == 50
    assert result["auto_import_base_version"] == 0
    assert result["auto_import_base_start"] == 0
    assert result["auto_import_caught_up_version"] is None

    client.items_since.return_value = (changed[50:], 80, False)
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
        second = sync_items(
            task_id="job-2",
            credential=_credential(),
            targets=[],
            auto_import_version=0,
            auto_import_start=50,
            is_active=lambda: True,
        )

    assert [item["item_key"] for item in second["auto_imports"]] == [
        f"ITEM{index:04}" for index in range(50, 75)
    ]
    assert second["auto_import_caught_up_version"] == 80
    assert client.items_since.call_args_list[-1].args[0] == 0
    assert client.items_since.call_args_list[-1].kwargs["start"] == 50


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


def test_attachment_cross_origin_redirect_never_forwards_zotero_api_key() -> None:
    redirect = MagicMock(status_code=302)
    redirect.headers = {"Location": "https://storage.example/paper.pdf"}
    final = MagicMock(status_code=200)
    final.headers = {"Content-Length": "4"}
    final.raise_for_status.return_value = None
    final.iter_content.return_value = [b"%PDF"]
    client = ZoteroClient(_credential())

    with (
        patch.object(client._session, "get", side_effect=[redirect, final]) as get,
        patch("src.zotero._require_public_url"),
        patch("src.zotero._require_global_peer"),
    ):
        assert client.download_attachment("ATTACH01") == b"%PDF"

    first_headers = get.call_args_list[0].kwargs["headers"]
    redirected_headers = get.call_args_list[1].kwargs["headers"]
    assert first_headers["Zotero-API-Key"] == "private-zotero-api-key"
    assert "Zotero-API-Key" not in redirected_headers
    redirect.close.assert_called_once_with()
    final.close.assert_called_once_with()


def test_public_pdf_rejects_private_connected_peer_after_public_dns_resolution() -> (
    None
):
    peer_socket = MagicMock()
    peer_socket.getpeername.return_value = ("127.0.0.1", 443)
    response = MagicMock()
    response.raw = SimpleNamespace(
        _connection=SimpleNamespace(sock=peer_socket),
    )
    response.is_redirect = False
    response.is_permanent_redirect = False
    session = MagicMock()
    session.get.return_value = response

    with (
        patch("src.zotero.requests.Session", return_value=session),
        patch(
            "src.zotero.socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", 443),
                )
            ],
        ),
    ):
        with pytest.raises(ZoteroJobError) as raised:
            _fetch_public_pdf("https://example.com/paper.pdf")

    assert raised.value.code == "zotero_pdf_unsafe_address"
    response.close.assert_called_once_with()


def test_public_pdf_session_ignores_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    session = MagicMock()
    session.get.side_effect = requests.RequestException("offline")

    with (
        patch("src.zotero.requests.Session", return_value=session),
        patch(
            "src.zotero.socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", 443),
                )
            ],
        ),
    ):
        with pytest.raises(ZoteroJobError):
            _fetch_public_pdf("https://example.com/paper.pdf")

    assert session.trust_env is False
