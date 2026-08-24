from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    DocumentResponse,
    LibraryPaperListIngestionEntry,
    LibraryPaperListPaperEntry,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperTagResponse,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.papers.application.library import (
    LibraryPaperPageAccess,
    LibraryPaperSummaryList,
    LibraryPaperUpdateResult,
)
from app.shared.domain import AppError, WorkspacePermission
from app.shared.domain.enums import DocumentProcessingStatus, PaperStatus
from app.tooling import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    ToolAccess,
    serialize_tool_success,
)
from app.tooling.dispatcher import _finalize_outcome
from app.tooling.library_paper_projection import (
    LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS,
    project_library_paper,
    project_updated_library_paper,
)
from app.tooling.contracts import ToolOutcome, ToolResourceLink
from app.tooling.json_document_paging import JsonDocumentPager
from app.tooling.legacy_result_budget import legacy_payload_json_utf8_budget
from app.tooling.workspace_contracts import (
    DocumentInput,
    JsonDocumentPageOutput,
    LibraryPaperListToolOutput,
    LibraryPaperPageInput,
    LibraryPaperToolOutput,
    ListLibraryPapersInput,
    UpdateLibraryPaperInput,
)
from app.tooling.workspace import MCP_TOOL_PROFILE, build_workspace_tool_catalog
from tests.test_project_tool_projection import _context, _handler


def _hostile_text(repetitions: int = 20_000) -> str:
    return '\x00\\"中🙂' * repetitions


def _library_paper(
    *,
    document_id: UUID | None = None,
    preview_url: str = "https://signed.example/private-preview",
    text: str | None = None,
) -> LibraryPaperResponse:
    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    value = text if text is not None else _hostile_text()
    short_override = value[:100_000]
    return LibraryPaperResponse(
        library_entry_id=uuid4(),
        user_id=7,
        status=PaperStatus.reading,
        last_accessed_at=now,
        metadata_overrides=DocumentMetadataOverrides(
            title=value[:1_000],
            authors=[value[:500] for _ in range(100)],
            abstract=short_override,
            institutions=[value[:500] for _ in range(100)],
            doi=value[:500],
            journal=value[:1_000],
            publisher=value[:1_000],
        ),
        is_public=False,
        preview_url=preview_url,
        tags=[
            LibraryPaperTagResponse(id=uuid4(), name=value, color=value)
            for _ in range(100)
        ],
        document=DocumentResponse(
            document_id=document_id or uuid4(),
            original_filename=value,
            mime_type=value,
            size_bytes=123,
            title=value,
            authors=[value for _ in range(100)],
            abstract=value,
            institutions=[value for _ in range(100)],
            keywords=[value for _ in range(100)],
            doi=value,
            journal=value,
            publisher=value,
            publish_date=None,
            summary=value,
            summary_citations=[
                ResponseCitation(text=value, index=index, document_id=value)
                for index in range(100)
            ],
            starter_questions=[value for _ in range(100)],
            processing_status=DocumentProcessingStatus.COMPLETED,
            parser_quality=value,
            parser_warning_code=value,
            created_at=now,
            updated_at=now,
        ),
        created_at=now,
        updated_at=now,
    )


def _list_entry(value: LibraryPaperResponse) -> LibraryPaperListPaperEntry:
    return LibraryPaperListPaperEntry.model_validate(value.model_dump())


def _page_access(
    paper: LibraryPaperResponse,
    *,
    revision: str = "library-revision-1",
    access_url: str | None = None,
    upper_bound: int | None = 8_000_000,
) -> LibraryPaperPageAccess:
    return LibraryPaperPageAccess(
        library_entry_id=paper.library_entry_id,
        document_id=paper.document.document_id,
        revision=revision,
        access_url=access_url,
        durable_json_utf8_upper_bound=upper_bound,
    )


def test_legacy_library_reads_preserve_full_page_and_object_semantics() -> None:
    paper = _library_paper(text="legacy full value")
    capabilities = MagicMock()
    capabilities.paper_library.list.return_value = LibraryPaperListResponse(
        items=[_list_entry(paper)],
        next_cursor=None,
        previous_cursor=None,
        total_count=1,
    )
    capabilities.paper_library.get.return_value = paper
    capabilities.paper_library.authorize_retained_size.return_value = _page_access(
        paper,
        upper_bound=10_000,
    )
    handler = _handler()

    listed = handler.list_library_papers(
        capabilities,
        _context(),
        ListLibraryPapersInput(limit=100),
    )
    fetched = handler.get_library_paper(
        capabilities,
        _context(),
        DocumentInput(document_id=paper.document.document_id),
    )

    assert capabilities.paper_library.list.call_args.kwargs["limit"] == 100
    assert (
        capabilities.paper_library.list.call_args.kwargs["maximum_retained_bytes"]
        == legacy_payload_json_utf8_budget()
    )
    assert "include_active_ingestions" not in (
        capabilities.paper_library.list.call_args.kwargs
    )
    assert LibraryPaperListResponse.model_validate(listed.payload).items[0] == (
        _list_entry(paper)
    )
    fetched_model = LibraryPaperResponse.model_validate(fetched.payload)
    assert fetched_model == paper
    assert fetched_model.preview_url == "https://signed.example/private-preview"


def test_legacy_library_paper_envelope_preflight_rejects_before_hydration() -> None:
    paper = _library_paper(text="must not hydrate")
    capabilities = MagicMock()
    capabilities.paper_library.authorize_retained_size.return_value = _page_access(
        paper,
        upper_bound=98_300,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_library_paper(
            capabilities,
            _context(),
            DocumentInput(document_id=paper.document.document_id),
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    capabilities.paper_library.get.assert_not_called()


def test_list_library_paper_summaries_caps_real_page_and_full_mcp_envelope() -> None:
    papers: list[LibraryPaperListPaperEntry | LibraryPaperListIngestionEntry] = [
        _list_entry(_library_paper()) for _ in range(LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS)
    ]
    capabilities = MagicMock()
    bounded_papers = [
        LibraryPaperListPaperEntry.model_validate(project_library_paper(item).value)
        for item in papers
        if isinstance(item, LibraryPaperListPaperEntry)
    ]
    capabilities.paper_library.list_summaries.return_value = LibraryPaperSummaryList(
        value=LibraryPaperListResponse(
            items=bounded_papers,
            next_cursor="signed-library-continuation",
            previous_cursor=None,
            total_count=100,
        ),
        content_truncated=True,
    )
    capabilities.paper_library.list.side_effect = AssertionError(
        "full path must not run"
    )

    raw = _handler().list_library_paper_summaries(
        capabilities,
        _context(),
        ListLibraryPapersInput(limit=100),
    )
    catalog = build_workspace_tool_catalog(
        ingestion=MagicMock(spec=PaperIngestionWorkflow),
        citations=MagicMock(spec=CitationWorkflow),
    )
    definition = catalog.definition_for(
        ToolAccess(
            profile_name=MCP_TOOL_PROFILE,
            permissions=frozenset(WorkspacePermission),
        ),
        "list_library_paper_summaries",
    )
    assert definition.outcome_projector is None
    outcome = _finalize_outcome(definition, raw)
    page = LibraryPaperListToolOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert capabilities.paper_library.list_summaries.call_args.kwargs["limit"] == (
        LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS
    )
    capabilities.paper_library.list.assert_not_called()
    assert page.next_cursor == "signed-library-continuation"
    assert page.content_truncated is True
    assert "get_library_paper_page" in page.guidance
    assert "list_jobs" in page.guidance
    assert all(item.entry_type == "paper" for item in page.items)
    assert all(
        isinstance(item, LibraryPaperListPaperEntry) and item.preview_url is None
        for item in page.items
    )
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES


def test_update_library_paper_projects_legacy_replay_idempotently() -> None:
    paper = _library_paper()
    legacy = ToolOutcome(
        payload=paper.model_dump(mode="json"),
        artifacts=[{"secret": "legacy-artifact"}],
        action={"kind": "legacy", "secret": "legacy-action"},
        resource_links=(
            ToolResourceLink(
                uri="https://signed.example/legacy-secret",
                name=_hostile_text(),
                description=_hostile_text(),
            ),
        ),
    )

    first = project_updated_library_paper(legacy)
    second = project_updated_library_paper(first)
    projected = LibraryPaperToolOutput.model_validate(first.payload)
    serialized = serialize_tool_success(first)

    assert second == first
    assert projected.content_truncated is True
    assert projected.preview_url is None
    assert first.sources == ()
    assert first.artifacts == []
    assert first.action == {
        "kind": "library_paper_updated",
        "library_entry_id": str(paper.library_entry_id),
        "document_id": str(paper.document.document_id),
        "status": "reading",
        "content_truncated": True,
    }
    assert first.resource_links == (
        ToolResourceLink(
            uri=f"scholens://papers/{paper.document.document_id}",
            name=first.resource_links[0].name,
            description=(
                "Canonical Scholens paper metadata. Use get_paper_content for bounded "
                "text."
            ),
        ),
    )
    assert "legacy-secret" not in json.dumps(
        serialized.structured_content,
        ensure_ascii=False,
    )
    assert "legacy-secret" not in serialized.text_content
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES


def test_update_library_paper_bounds_every_duplicate_envelope_lane() -> None:
    paper = _library_paper()
    capabilities = MagicMock()
    capabilities.paper_library.update.side_effect = AssertionError(
        "MCP update must not hydrate the HTTP response"
    )
    capabilities.paper_library.update_summary.return_value = LibraryPaperUpdateResult(
        response=paper,
        changed=True,
        content_truncated=True,
    )
    handler = _handler()

    raw = handler.update_library_paper(
        capabilities,
        _context(),
        UpdateLibraryPaperInput(
            document_id=paper.document.document_id,
            idempotency_key="library-update-budget",
            status=PaperStatus.completed,
        ),
    )
    catalog = build_workspace_tool_catalog(
        ingestion=MagicMock(spec=PaperIngestionWorkflow),
        citations=MagicMock(spec=CitationWorkflow),
    )
    definition = catalog.definition_for(
        ToolAccess(
            profile_name=MCP_TOOL_PROFILE,
            permissions=frozenset(WorkspacePermission),
        ),
        "update_library_paper",
    )
    assert definition.outcome_projector is project_updated_library_paper
    outcome = _finalize_outcome(definition, raw)

    projected = LibraryPaperToolOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert projected.content_truncated is True
    assert projected.preview_url is None
    assert paper.preview_url == "https://signed.example/private-preview"
    assert outcome.action == {
        "kind": "library_paper_updated",
        "library_entry_id": str(paper.library_entry_id),
        "document_id": str(paper.document.document_id),
        "status": "reading",
        "content_truncated": True,
    }
    assert "paper" not in outcome.action
    capabilities.paper_library.update.assert_not_called()
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES


def test_library_paper_pages_reconstruct_lossless_json_once_and_rotate_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    base = _library_paper(
        document_id=document_id,
        preview_url="https://signed.example/first",
        text="small metadata",
    )
    long_abstract = _hostile_text()
    first = base.model_copy(
        update={
            "metadata_overrides": base.metadata_overrides.model_copy(
                update={"abstract": long_abstract[:100_000]}
            ),
            "document": base.document.model_copy(
                update={"abstract": long_abstract, "summary": long_abstract}
            ),
        }
    )
    capabilities = MagicMock()
    capabilities.paper_library.get.return_value = first
    access_calls = 0

    def authorize_revision(**_arguments: object) -> LibraryPaperPageAccess:
        nonlocal access_calls
        access_calls += 1
        return _page_access(
            first,
            access_url=(
                "https://signed.example/first"
                if access_calls <= 2
                else "https://signed.example/rotated"
            ),
            upper_bound=None,
        )

    capabilities.paper_library.authorize_revision.side_effect = authorize_revision
    capabilities.paper_library.authorize_retained_size.return_value = _page_access(
        first,
        access_url="https://signed.example/first",
    )
    handler = _handler()
    original_init = JsonDocumentPager.__init__
    serialization_count = 0

    def counted_init(self: JsonDocumentPager, value: object) -> None:
        nonlocal serialization_count
        serialization_count += 1
        original_init(self, value)

    monkeypatch.setattr(JsonDocumentPager, "__init__", counted_init)

    chunks: list[str] = []
    cursor: str | None = None
    access_urls: list[str] = []
    for _ in range(100):
        outcome = handler.get_library_paper_page(
            capabilities,
            _context(),
            LibraryPaperPageInput(
                document_id=document_id,
                cursor=cursor,
                max_utf8_bytes=32_000,
            ),
        )
        page = JsonDocumentPageOutput.model_validate(outcome.payload)
        assert len(page.content.encode("utf-8")) <= 32_000
        assert serialize_tool_success(outcome).call_tool_result_utf8_bytes < (
            DEFAULT_TOOL_OUTPUT_BYTES
        )
        chunks.append(page.content)
        if page.access_url is not None:
            access_urls.append(page.access_url)
        cursor = page.next_cursor
        if page.complete:
            break
    else:  # pragma: no cover - protects the bounded test loop
        pytest.fail("Library paper JSON did not terminate")

    reconstructed = json.loads("".join(chunks))
    expected = first.model_dump(mode="json")
    expected["preview_url"] = None
    assert reconstructed == expected
    assert access_urls[0] == "https://signed.example/first"
    assert "https://signed.example/rotated" in access_urls
    assert serialization_count == 1
    assert capabilities.paper_library.get.call_count == 1
    assert capabilities.paper_library.authorize_retained_size.call_count == 1


def test_library_paper_page_cursor_rejects_tamper_actor_and_revision_change() -> None:
    base = _library_paper(text="small metadata")
    paper = base.model_copy(
        update={
            "document": base.document.model_copy(update={"abstract": "界🙂" * 20_000})
        }
    )
    capabilities = MagicMock()
    capabilities.paper_library.get.return_value = paper
    capabilities.paper_library.authorize_revision.return_value = _page_access(
        paper,
        upper_bound=None,
    )
    capabilities.paper_library.authorize_retained_size.return_value = _page_access(
        paper
    )
    handler = _handler()
    request = LibraryPaperPageInput(
        document_id=paper.document.document_id,
        max_utf8_bytes=1_024,
    )
    first = JsonDocumentPageOutput.model_validate(
        handler.get_library_paper_page(capabilities, _context(), request).payload
    )
    assert first.next_cursor is not None

    tampered = first.next_cursor[:-1] + ("A" if first.next_cursor[-1] != "A" else "B")
    with pytest.raises(AppError) as raised:
        handler.get_library_paper_page(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": tampered}),
        )
    assert raised.value.code == "library_paper_cursor_invalid"
    base_context = _context()
    cross_actor = replace(
        base_context,
        actor=base_context.actor.model_copy(
            update={"id": 8, "email": "other@example.com"}
        ),
    )
    with pytest.raises(AppError) as raised:
        handler.get_library_paper_page(
            capabilities,
            cross_actor,
            request.model_copy(update={"cursor": first.next_cursor}),
        )
    assert raised.value.code == "library_paper_cursor_invalid"

    changed_document = paper.document.model_copy(
        update={
            "abstract": "changed " + (paper.document.abstract or ""),
            "updated_at": paper.document.updated_at + timedelta(seconds=1),
        }
    )
    capabilities.paper_library.get.return_value = paper.model_copy(
        update={"document": changed_document}
    )
    capabilities.paper_library.authorize_revision.return_value = _page_access(
        paper,
        revision="library-revision-2",
        upper_bound=None,
    )
    with pytest.raises(AppError) as raised:
        handler.get_library_paper_page(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": first.next_cursor}),
        )
    assert raised.value.code == "library_paper_cursor_invalid"


def test_library_paper_page_size_preflight_rejects_before_full_hydration() -> None:
    paper = _library_paper(text="must not hydrate")
    capabilities = MagicMock()
    capabilities.paper_library.authorize_revision.return_value = _page_access(
        paper,
        upper_bound=None,
    )
    capabilities.paper_library.authorize_retained_size.return_value = _page_access(
        paper,
        upper_bound=70 * 1024 * 1024,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_library_paper_page(
            capabilities,
            _context(),
            LibraryPaperPageInput(document_id=paper.document.document_id),
        )

    assert raised.value.code == "json_document_paging_limit_exceeded"
    capabilities.paper_library.get.assert_not_called()
