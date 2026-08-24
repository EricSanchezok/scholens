from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import timedelta
from threading import Event
from unittest.mock import MagicMock

import pytest

from app.modules.research.application.contracts import (
    AudioOverviewContent,
    ResearchItemResponse,
)
from app.modules.papers.application.details import PaperDetailsRevision
from app.modules.research.application.items import ResearchItemPageAccess
from app.shared.domain import AppError
from app.shared.domain.enums import ResearchItemKind
from app.tooling.workspace_contracts import (
    AnnotationThreadPageInput,
    DocumentInput,
    JsonDocumentPageOutput,
    PaperMetadataPageInput,
    ResearchOutputPageInput,
)
from app.tooling.json_document_paging import JsonDocumentPager, JsonDocumentPagerCache
from tests.test_mcp_resources import _document
from tests.test_workspace_research_outputs import _context, _handler, _research_item


def _large_audio_item(*, access_url: str, transcript: str) -> ResearchItemResponse:
    document = _document()
    item = _research_item(
        kind=ResearchItemKind.AUDIO_OVERVIEW,
        document_id=document.document_id,
        title="Bounded audio",
        updated_at=document.updated_at,
    )
    return item.model_copy(
        update={
            "audio_overview": AudioOverviewContent(
                title="Bounded audio",
                transcript=transcript,
                citations=[],
                audio_url=access_url,
                voice_id="voice",
                model_version="v1",
            )
        }
    )


def _page_access(
    item: ResearchItemResponse,
    *,
    revision: str = "revision-1",
    upper_bound: int = 8_000_000,
    access_url: str | None = None,
) -> ResearchItemPageAccess:
    return ResearchItemPageAccess(
        item_id=item.id,
        kind=item.kind,
        revision=revision,
        durable_json_utf8_upper_bound=upper_bound,
        access_url=access_url,
    )


def test_research_output_pages_reconstruct_large_json_once_and_rotate_access_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = "多语言 transcript 🔬 " * 8_000
    first_item = _large_audio_item(
        access_url="https://signed.example/first",
        transcript=transcript,
    )
    capabilities = MagicMock()
    capabilities.research_items.get_item.return_value = first_item
    access_calls = 0

    def authorize_page(**_arguments: object) -> ResearchItemPageAccess:
        nonlocal access_calls
        access_calls += 1
        return _page_access(
            first_item,
            access_url=(
                "https://signed.example/first"
                if access_calls <= 2
                else "https://signed.example/second"
            ),
        )

    capabilities.research_items.authorize_page.side_effect = authorize_page
    handler = _handler()
    original_init = JsonDocumentPager.__init__
    serialization_count = 0

    def counted_init(self: JsonDocumentPager, value: object) -> None:
        nonlocal serialization_count
        serialization_count += 1
        original_init(self, value)

    monkeypatch.setattr(JsonDocumentPager, "__init__", counted_init)
    request = ResearchOutputPageInput(
        item_id=first_item.id,
        max_utf8_bytes=4_096,
    )

    chunks: list[str] = []
    cursor: str | None = None
    access_urls: list[str] = []
    for _ in range(100):
        outcome = handler.get_research_output_page(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": cursor}),
        )
        page = JsonDocumentPageOutput.model_validate(outcome.payload)
        assert len(page.content.encode("utf-8")) <= 4_096
        assert page.start_utf8_byte == sum(
            len(chunk.encode("utf-8")) for chunk in chunks
        )
        chunks.append(page.content)
        if page.access_url is not None:
            access_urls.append(page.access_url)
        cursor = page.next_cursor
        if page.complete:
            break
    else:  # pragma: no cover - protects the bounded test loop
        pytest.fail("research output did not terminate")

    reconstructed = json.loads("".join(chunks))
    assert reconstructed["audio_overview"]["transcript"] == transcript
    assert "audio_url" not in reconstructed["audio_overview"]
    assert reconstructed["audio_overview"]["audio_access"] == (
        "Use the page-level access_url."
    )
    assert access_urls[0] == "https://signed.example/first"
    assert "https://signed.example/second" in access_urls
    assert serialization_count == 1
    assert capabilities.research_items.get_item.call_count == 1


def test_research_output_cursor_rejects_changed_persistent_content() -> None:
    item = _large_audio_item(
        access_url="https://signed.example/first",
        transcript="x" * 20_000,
    )
    audio = AudioOverviewContent.model_validate(item.audio_overview)
    changed = item.model_copy(
        update={
            "audio_overview": audio.model_copy(
                update={"transcript": "changed " + audio.transcript}
            ),
            "updated_at": item.updated_at + timedelta(seconds=1),
        }
    )
    capabilities = MagicMock()
    capabilities.research_items.get_item.side_effect = [item, changed]
    capabilities.research_items.authorize_page.side_effect = [
        _page_access(item, revision="revision-1"),
        _page_access(item, revision="revision-1"),
        _page_access(changed, revision="revision-2"),
        _page_access(changed, revision="revision-2"),
    ]
    handler = _handler()
    request = ResearchOutputPageInput(item_id=item.id, max_utf8_bytes=1_024)
    first = JsonDocumentPageOutput.model_validate(
        handler.get_research_output_page(capabilities, _context(), request).payload
    )
    assert first.next_cursor is not None

    with pytest.raises(AppError) as raised:
        handler.get_research_output_page(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": first.next_cursor}),
        )
    assert raised.value.code == "research_output_cursor_invalid"


def test_research_output_page_cache_is_actor_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _large_audio_item(
        access_url="https://signed.example/access",
        transcript="x" * 20_000,
    )
    capabilities = MagicMock()
    capabilities.research_items.get_item.return_value = item
    capabilities.research_items.authorize_page.return_value = _page_access(item)
    handler = _handler()
    original_init = JsonDocumentPager.__init__
    serialization_count = 0

    def counted_init(self: JsonDocumentPager, value: object) -> None:
        nonlocal serialization_count
        serialization_count += 1
        original_init(self, value)

    monkeypatch.setattr(JsonDocumentPager, "__init__", counted_init)
    request = ResearchOutputPageInput(item_id=item.id, max_utf8_bytes=1_024)

    handler.get_research_output_page(capabilities, _context(7), request)
    handler.get_research_output_page(capabilities, _context(8), request)

    assert serialization_count == 2


@pytest.mark.parametrize(
    "kind",
    [ResearchItemKind.ANNOTATION_THREAD, ResearchItemKind.DATA_TABLE],
)
def test_annotation_and_data_table_pages_reuse_one_canonical_serialization(
    kind: ResearchItemKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    item = _research_item(
        kind=kind,
        document_id=document.document_id,
        title="界🙂" * 20_000,
        updated_at=document.updated_at,
    )
    capabilities = MagicMock()
    capabilities.research_items.get_item.return_value = item
    capabilities.research_items.authorize_page.return_value = _page_access(item)
    handler = _handler()
    original_init = JsonDocumentPager.__init__
    serialization_count = 0

    def counted_init(self: JsonDocumentPager, value: object) -> None:
        nonlocal serialization_count
        serialization_count += 1
        original_init(self, value)

    monkeypatch.setattr(JsonDocumentPager, "__init__", counted_init)
    if kind is ResearchItemKind.ANNOTATION_THREAD:
        annotation_request = AnnotationThreadPageInput(
            thread_id=item.id,
            max_utf8_bytes=1_024,
        )
        first = JsonDocumentPageOutput.model_validate(
            handler.get_annotation_thread_page(
                capabilities,
                _context(),
                annotation_request,
            ).payload
        )
        assert first.next_cursor is not None
        handler.get_annotation_thread_page(
            capabilities,
            _context(),
            annotation_request.model_copy(update={"cursor": first.next_cursor}),
        )
    else:
        output_request = ResearchOutputPageInput(
            item_id=item.id,
            max_utf8_bytes=1_024,
        )
        first = JsonDocumentPageOutput.model_validate(
            handler.get_research_output_page(
                capabilities,
                _context(),
                output_request,
            ).payload
        )
        assert first.next_cursor is not None
        handler.get_research_output_page(
            capabilities,
            _context(),
            output_request.model_copy(update={"cursor": first.next_cursor}),
        )

    assert serialization_count == 1


def test_get_paper_returns_lossless_bounded_metadata_page() -> None:
    document = _document().model_copy(update={"abstract": "界" * 20_000})
    capabilities = MagicMock()
    capabilities.paper_details.return_value = document
    capabilities.paper_details.authorize_revision.return_value = PaperDetailsRevision(
        document_id=document.document_id,
        revision=document.updated_at.isoformat(),
    )
    capabilities.paper_details.authorize_retained_size.return_value = (
        PaperDetailsRevision(
            document_id=document.document_id,
            revision=document.updated_at.isoformat(),
            durable_json_utf8_upper_bound=1_000_000,
        )
    )
    handler = _handler()

    outcome = handler.get_paper_page(
        capabilities,
        _context(),
        PaperMetadataPageInput(
            document_id=document.document_id,
            max_utf8_bytes=2_048,
        ),
    )
    page = JsonDocumentPageOutput.model_validate(outcome.payload)

    assert page.complete is False
    assert page.next_cursor is not None
    assert len(page.content.encode("utf-8")) <= 2_048
    capabilities.paper_collection_access.assert_called_once()
    capabilities.paper_details.assert_called_once()


def test_paper_metadata_size_preflight_rejects_before_full_hydration() -> None:
    document = _document()
    capabilities = MagicMock()
    capabilities.paper_details.authorize_revision.return_value = PaperDetailsRevision(
        document_id=document.document_id,
        revision=document.updated_at.isoformat(),
    )
    capabilities.paper_details.authorize_retained_size.return_value = (
        PaperDetailsRevision(
            document_id=document.document_id,
            revision=document.updated_at.isoformat(),
            durable_json_utf8_upper_bound=70 * 1024 * 1024,
        )
    )

    with pytest.raises(AppError) as raised:
        _handler().get_paper_page(
            capabilities,
            _context(),
            PaperMetadataPageInput(document_id=document.document_id),
        )

    assert raised.value.code == "json_document_paging_limit_exceeded"
    capabilities.paper_details.assert_not_called()


def test_legacy_paper_envelope_preflight_rejects_before_full_hydration() -> None:
    document = _document()
    capabilities = MagicMock()
    capabilities.paper_details.authorize_retained_size.return_value = (
        PaperDetailsRevision(
            document_id=document.document_id,
            revision=document.updated_at.isoformat(),
            # This passed the former half-budget check but can exceed the MCP
            # envelope limit once hostile JSON is duplicated and escaped.
            durable_json_utf8_upper_bound=98_300,
        )
    )

    with pytest.raises(AppError) as raised:
        _handler().get_paper(
            capabilities,
            _context(),
            DocumentInput(document_id=document.document_id),
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    capabilities.paper_details.assert_not_called()


def test_concurrent_paper_metadata_pages_hydrate_once() -> None:
    document = _document().model_copy(update={"abstract": "shared " * 5_000})
    capabilities = MagicMock()
    access = PaperDetailsRevision(
        document_id=document.document_id,
        revision=document.updated_at.isoformat(),
    )
    capabilities.paper_details.authorize_revision.return_value = access
    capabilities.paper_details.authorize_retained_size.return_value = (
        PaperDetailsRevision(
            document_id=document.document_id,
            revision=access.revision,
            durable_json_utf8_upper_bound=1_000_000,
        )
    )
    hydrate_started = Event()
    release_hydrate = Event()

    def hydrate(**_arguments: object):
        hydrate_started.set()
        assert release_hydrate.wait(timeout=5)
        return document

    capabilities.paper_details.side_effect = hydrate
    handler = _handler()
    request = PaperMetadataPageInput(
        document_id=document.document_id,
        max_utf8_bytes=1_024,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(handler.get_paper_page, capabilities, _context(), request)
            for _index in range(8)
        ]
        assert hydrate_started.wait(timeout=5)
        release_hydrate.set()
        pages = [
            JsonDocumentPageOutput.model_validate(future.result(timeout=5).payload)
            for future in futures
        ]

    assert capabilities.paper_details.call_count == 1
    assert all(page.content_sha256 == pages[0].content_sha256 for page in pages)


def test_page_handler_rejects_documents_above_the_controlled_cache_limit() -> None:
    item = _large_audio_item(
        access_url="https://signed.example/access",
        transcript="x" * 20_000,
    )
    capabilities = MagicMock()
    capabilities.research_items.get_item.return_value = item
    capabilities.research_items.authorize_page.return_value = _page_access(
        item,
        upper_bound=1_000,
    )
    handler = _handler()
    handler._json_document_page_cache = JsonDocumentPagerCache(
        max_entries=1,
        max_total_utf8_bytes=1_024,
        max_entry_utf8_bytes=1_024,
    )

    with pytest.raises(AppError) as raised:
        handler.get_research_output_page(
            capabilities,
            _context(),
            ResearchOutputPageInput(item_id=item.id, max_utf8_bytes=1_024),
        )

    assert raised.value.code == "json_document_paging_limit_exceeded"
    assert raised.value.kind.value == "payload_too_large"
    assert raised.value.details is not None
    assert raised.value.details["maximum_utf8_bytes"] == 1_024


@pytest.mark.parametrize(
    "kind",
    [ResearchItemKind.ANNOTATION_THREAD, ResearchItemKind.DATA_TABLE],
)
def test_research_page_size_preflight_rejects_before_full_hydration(
    kind: ResearchItemKind,
) -> None:
    document = _document()
    item = _research_item(
        kind=kind,
        document_id=document.document_id,
        title="small fixture that must not be hydrated",
        updated_at=document.updated_at,
    )
    capabilities = MagicMock()
    capabilities.research_items.authorize_page.return_value = _page_access(
        item,
        upper_bound=70 * 1024 * 1024,
    )
    handler = _handler()

    with pytest.raises(AppError) as raised:
        if kind is ResearchItemKind.ANNOTATION_THREAD:
            handler.get_annotation_thread_page(
                capabilities,
                _context(),
                AnnotationThreadPageInput(thread_id=item.id),
            )
        else:
            handler.get_research_output_page(
                capabilities,
                _context(),
                ResearchOutputPageInput(item_id=item.id),
            )

    assert raised.value.code == "json_document_paging_limit_exceeded"
    capabilities.research_items.get_item.assert_not_called()


def test_concurrent_same_revision_pages_hydrate_research_output_once() -> None:
    item = _large_audio_item(
        access_url="https://signed.example/access",
        transcript="shared transcript " * 2_000,
    )
    capabilities = MagicMock()
    capabilities.research_items.authorize_page.return_value = _page_access(
        item,
        access_url="https://signed.example/access",
    )
    hydrate_started = Event()
    release_hydrate = Event()

    def hydrate(**_arguments: object) -> ResearchItemResponse:
        hydrate_started.set()
        assert release_hydrate.wait(timeout=2)
        return item

    capabilities.research_items.get_item.side_effect = hydrate
    handler = _handler()
    request = ResearchOutputPageInput(item_id=item.id, max_utf8_bytes=1_024)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                handler.get_research_output_page,
                capabilities,
                _context(),
                request,
            )
            for _ in range(8)
        ]
        assert hydrate_started.wait(timeout=2)
        assert handler._json_document_page_cache.active_builds == 1
        release_hydrate.set()
        pages = [
            JsonDocumentPageOutput.model_validate(future.result(timeout=2).payload)
            for future in futures
        ]

    assert capabilities.research_items.get_item.call_count == 1
    assert all(page.content_sha256 == pages[0].content_sha256 for page in pages)
