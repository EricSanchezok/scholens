import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests

from app.bootstrap.adapters.zotero_operations import DefaultZoteroOperations
from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.modules.integrations.zotero.application.contracts import ZoteroLibraryPage
from app.modules.integrations.zotero.application.zotero import (
    ZoteroCredentials,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
)
from app.modules.integrations.zotero.infrastructure.client import ZoteroApiClient
from app.modules.integrations.zotero.infrastructure.client import (
    ZoteroAttachmentScanLimitError,
)
from app.shared.application import Actor, OperationContextFactory, SignedCursorCodec
from app.shared.domain import AppError


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self.capabilities = capabilities

    def query(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)


def test_zotero_api_caps_pages_at_one_hundred_and_sends_server_filters() -> None:
    response = MagicMock()
    response.json.return_value = []
    response.headers = {"Total-Results": "0", "Last-Modified-Version": "12"}
    response.status_code = 200
    response.raise_for_status.return_value = None
    client = ZoteroApiClient("42", "secret")
    with patch.object(client, "_request", return_value=response) as request:
        page = client.get_top_importable_items_page(
            limit=500,
            start=100,
            query="transformer",
            collection_key="COLLECTION",
            item_type="preprint",
            sort="title",
            direction="asc",
        )

    assert page.library_version == 12
    assert request.call_args.kwargs["params"] == {
        "limit": 100,
        "start": 100,
        "sort": "title",
        "direction": "asc",
        "itemType": "preprint",
        "q": "transformer",
        "qmode": "titleCreatorYear",
    }


def test_zotero_metadata_rejects_cross_origin_redirect_without_leaking_key() -> None:
    redirect = MagicMock(status_code=302)
    redirect.headers = {"Location": "https://storage.example/items.json"}
    client = ZoteroApiClient("42", "secret")

    with patch.object(client._session, "request", return_value=redirect) as request:
        with pytest.raises(requests.exceptions.InvalidURL):
            client.current_library_version()

    assert request.call_count == 1
    assert request.call_args.kwargs["headers"]["Zotero-API-Key"] == "secret"
    assert redirect.close.called
    assert client._session.trust_env is False


@pytest.mark.parametrize(
    ("header", "expected"),
    [("invalid", 0), ("999999", 10), ("-50", 0)],
)
def test_zotero_api_safely_caps_provider_backoff(
    header: str,
    expected: int,
) -> None:
    response = MagicMock(status_code=200)
    response.headers = {"Backoff": header}
    response.raise_for_status.return_value = None
    client = ZoteroApiClient("42", "secret")

    with (
        patch.object(client._session, "request", return_value=response),
        patch(
            "app.modules.integrations.zotero.infrastructure.client.time.sleep"
        ) as sleep,
    ):
        returned = client._request("GET", "https://api.zotero.org/keys/current")

    assert returned is response
    sleep.assert_called_once_with(expected)


def test_visible_item_attachment_lookup_fails_instead_of_truncating() -> None:
    response = MagicMock()
    response.headers = {"Total-Results": "101"}
    response.json.return_value = [
        {"data": {"itemType": "attachment", "linkMode": "linked_url"}}
        for _ in range(100)
    ]
    client = ZoteroApiClient("42", "secret")

    with patch.object(client, "_request", return_value=response) as request:
        with pytest.raises(ZoteroAttachmentScanLimitError):
            client.get_stored_pdf_parent_keys(
                ["ITEM0001"],
                max_children_per_item=100,
            )

    assert "/items/ITEM0001/children" in request.call_args.args[1]
    response.close.assert_called_once_with()


def test_visible_item_attachment_lookup_classifies_only_requested_page() -> None:
    response = MagicMock()
    response.headers = {"Total-Results": "1"}
    response.json.return_value = [
        {
            "data": {
                "contentType": "application/pdf",
                "itemType": "attachment",
                "linkMode": "imported_file",
            }
        }
    ]
    client = ZoteroApiClient("42", "secret")

    with patch.object(client, "_request", return_value=response) as request:
        parents = client.get_stored_pdf_parent_keys(["ITEM0001"])

    assert parents == {"ITEM0001"}
    assert request.call_args.kwargs["params"] == {
        "itemType": "attachment",
        "limit": 100,
        "start": 0,
    }


@pytest.mark.asyncio
async def test_cancelled_canonical_upload_tracks_the_background_write() -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def blocked_to_thread(*_args: object, **_kwargs: object) -> None:
        started.set()
        await finish.wait()

    operations = DefaultZoteroOperations()
    with patch(
        "app.bootstrap.adapters.zotero_operations.asyncio.to_thread",
        side_effect=blocked_to_thread,
    ):
        task = asyncio.create_task(operations.upload_pdf(content=b"%PDF-staged"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(operations._detached_uploads) == 1
        finish.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert operations._detached_uploads == set()


def test_library_cursor_is_bound_to_owner_and_filters() -> None:
    item = ZoteroItemSnapshot(
        item_key="ITEM1",
        title="Paper",
        authors=(),
        abstract=None,
        publish_date=None,
        doi=None,
        tags=(),
        date_added=None,
        item_type="journalArticle",
        venue=None,
        collection_keys=(),
        has_pdf_attachment=True,
        has_resolvable_source=False,
        has_metadata=True,
        version=1,
    )
    snapshot = ZoteroLibrarySnapshot(
        items=(item,),
        total_count=2,
        library_version=1,
    )
    zotero = MagicMock()
    zotero.prepare_library.return_value = ZoteroCredentials(
        user_id="42",
        api_key="secret",
        revision=uuid4(),
    )
    zotero.library.return_value = ZoteroLibraryPage(
        items=[],
        total_count=2,
        remaining_slots=10,
    )
    operations = MagicMock()
    operations.fetch_library.return_value = snapshot
    workflow = ZoteroWorkflow(
        executor=_Executor(SimpleNamespace(zotero=zotero)),  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
        cursors=SignedCursorCodec(
            "test-zotero-cursor-key",
            revision="zotero-test-v1",
            error_code="zotero_cursor_invalid",
        ),
    )

    page = workflow.library(
        actor=_actor(),
        cursor=None,
        query="paper",
        collection_key=None,
        item_type=None,
        sort="modified_desc",
        limit=1,
    )
    assert page.next_cursor is not None

    with pytest.raises(AppError) as raised:
        workflow.library(
            actor=_actor(),
            cursor=page.next_cursor,
            query="different",
            collection_key=None,
            item_type=None,
            sort="modified_desc",
            limit=1,
        )
    assert raised.value.code == "zotero_cursor_invalid"
