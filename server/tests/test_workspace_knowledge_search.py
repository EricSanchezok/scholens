from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperSearchCandidate,
    PaperSearchCandidatePage,
    PaperSearchFilters,
    PaperSearchRequest,
    PaperSearchResult,
    PaperSearchSnippet,
)
from app.modules.research.application.catalog import ResearchOutputCatalogScope
from app.modules.research.application.catalog import (
    ResearchOutputPagePosition,
    ResearchOutputSummaryPage,
)
from app.modules.research.application.contracts import (
    AnnotationThreadCapabilities,
    AnnotationThreadSummaryResponse,
    DocumentResearchAudience,
    PersonalResearchAudience,
    ResearchCreatorResponse,
    ResearchOutputCreatorSummary,
    ResearchOutputSourceSummary,
    ResearchOutputSummary,
)
from app.modules.research.application.search import (
    ResearchSearchCandidatePage,
    ResearchSearchComment,
    ResearchSearchPosition,
    ResearchSearchResult,
    ResearchSearchScope,
)
from app.modules.research.application.items import (
    AnnotationThreadSummaryKeyset,
    AnnotationThreadSummaryPage,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SignedCursorCodec,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchItemKind,
)
from app.tooling.contracts import DEFAULT_TOOL_OUTPUT_BYTES, ToolExecutionContext
from app.tooling.knowledge_search_projection import (
    KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS,
    KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
)
from app.tooling.knowledge_search_paging import (
    KnowledgeProducerPosition,
    KnowledgeSearchCursorState,
    encode_knowledge_cursor,
    knowledge_cursor_fingerprint,
)
from app.tooling.results import serialize_tool_success
from app.tooling.workspace_contracts import (
    KnowledgeSearchOutput,
    AllAccessibleKnowledgeScope,
    LibraryKnowledgeScope,
    ListAnnotationThreadsInput,
    PaperKnowledgeScope,
    ProjectKnowledgeScope,
    SearchKnowledgeInput,
    ThreadListOutput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _context() -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(),
        operation=operation,
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="knowledge-search-test",
        client_ip="test",
    )


def test_search_scope_schema_includes_complete_object_examples() -> None:
    scope_schema = SearchKnowledgeInput.model_json_schema()["properties"]["scope"]

    assert scope_schema["examples"] == [
        {"kind": "library"},
        {"kind": "all_accessible"},
        {"kind": "project", "project_id": "00000000-0000-0000-0000-000000000000"},
        {"kind": "paper", "document_id": "00000000-0000-0000-0000-000000000000"},
    ]


def test_knowledge_search_rejects_previous_paper_ranking_cursor_revision() -> None:
    request = SearchKnowledgeInput(
        query="compression",
        scope=LibraryKnowledgeScope(),
    )
    fingerprint = json.dumps(
        request.model_dump(mode="json", exclude={"cursor"}),
        separators=(",", ":"),
        sort_keys=True,
    )
    legacy = SignedCursorCodec(
        "test-secret",
        revision="scholens-knowledge:1",
        error_code="knowledge_search_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    stale_request = request.model_copy(
        update={"cursor": legacy.encode(fingerprint=fingerprint, offset=10)}
    )

    with pytest.raises(AppError) as error:
        _handler().search_knowledge(
            _capabilities([]),
            _context(),
            stale_request,
        )

    assert error.value.code == "knowledge_search_cursor_invalid"
    assert error.value.kind is FailureKind.INVALID_ARGUMENT


def _thread(*, document_id: UUID, project_id: UUID | None) -> ResearchSearchResult:
    return ResearchSearchResult(
        id=uuid4(),
        document_id=document_id,
        project_id=project_id,
        document_title="Paper",
        quote_text="chain of thought compression",
        position=None,
        role="assistant",
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        matching_comments=[],
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="test-secret",
    )


def _capabilities(threads: list[ResearchSearchResult]) -> MagicMock:
    capabilities = MagicMock()
    capabilities.paper_search.candidate_page.return_value = PaperSearchCandidatePage(
        items=[], total=0
    )
    capabilities.research_search.candidate_page.return_value = (
        ResearchSearchCandidatePage(
            items=tuple(threads[:25]), has_more=len(threads) > 25
        )
    )
    capabilities.research_output_catalog.candidate_page.return_value = (
        ResearchOutputSummaryPage(
            items=[],
            positions=[],
            has_more=False,
            total_count=None,
        )
    )
    return capabilities


def _output_page(
    items: list[ResearchOutputSummary],
    *,
    has_more: bool = False,
) -> ResearchOutputSummaryPage:
    return ResearchOutputSummaryPage(
        items=items,
        positions=[
            ResearchOutputPagePosition(
                key=item.updated_at.isoformat(),
                item_id=item.item_id,
            )
            for item in items
        ],
        has_more=has_more,
        total_count=None,
    )


def _paper_candidate_page(
    items: list[PaperSearchResult],
    *,
    total: int,
) -> PaperSearchCandidatePage:
    return PaperSearchCandidatePage(
        items=[
            PaperSearchCandidate(
                document_id=item.document_id,
                title=item.title,
                abstract=item.abstract,
                created_at=item.created_at,
                last_accessed_at=item.last_accessed_at,
                snippets=item.snippets,
            )
            for item in items
        ],
        total=total,
    )


def _request_with_cursor_state(
    *,
    handler: WorkspaceToolHandlers,
    context: ToolExecutionContext,
    request: SearchKnowledgeInput,
    state: KnowledgeSearchCursorState,
) -> SearchKnowledgeInput:
    fingerprint = knowledge_cursor_fingerprint(
        actor_id=context.actor.id,
        request=request,
    )
    return request.model_copy(
        update={
            "cursor": encode_knowledge_cursor(
                codec=handler._knowledge_cursors,  # noqa: SLF001 - cursor black-box test
                state=state,
                fingerprint=fingerprint,
            )
        }
    )


def _output_summary(
    *,
    item_id: UUID | None = None,
    document_id: UUID | None = None,
    updated_at: datetime | None = None,
    text: str = "Compression comparison",
) -> ResearchOutputSummary:
    resolved_document_id = document_id or uuid4()
    now = datetime(2026, 8, 16, tzinfo=UTC)
    resolved_item_id = item_id or uuid4()
    return ResearchOutputSummary(
        item_id=resolved_item_id,
        kind=ResearchItemKind.DATA_TABLE,
        audience=DocumentResearchAudience(document_id=resolved_document_id),
        target_document_id=resolved_document_id,
        title=text[:240],
        excerpt=text[:1_200],
        creator=ResearchOutputCreatorSummary(id=7, display_name="Researcher"),
        created_at=now,
        updated_at=updated_at or now,
        source=ResearchOutputSourceSummary(
            audience_type="document",
            audience_id=resolved_document_id,
            title="Paper",
        ),
        resource_uri=f"scholens://research-outputs/{resolved_item_id}",
    )


def _annotation_summary(document_id: UUID) -> AnnotationThreadSummaryResponse:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    return AnnotationThreadSummaryResponse(
        id=uuid4(),
        audience=PersonalResearchAudience(),
        target_document_id=document_id,
        created_by=ResearchCreatorResponse(id=7, display_name="Researcher"),
        created_at=now,
        quote_text="chain of thought compression",
        position=None,
        color=AnnotationColor.YELLOW,
        role="assistant",
        mode=AnnotationThreadMode.HIGHLIGHT,
        comment_count=0,
        last_activity_at=now,
        status=AnnotationThreadStatus.OPEN,
        resolved_by=None,
        resolved_at=None,
        capabilities=AnnotationThreadCapabilities(
            reply=True,
            recolor=True,
            resolve=True,
            reopen=False,
            delete=True,
        ),
        comments=[],
    )


def test_library_annotation_search_pushes_scope_before_candidate_limit() -> None:
    personal_document_id = uuid4()
    capabilities = _capabilities(
        [_thread(document_id=personal_document_id, project_id=None)]
    )

    outcome = _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput(
            query="compression",
            scope=LibraryKnowledgeScope(),
            kinds=["annotation_thread"],
        ),
    )
    result = KnowledgeSearchOutput.model_validate(outcome.payload)

    assert len(result.items) == 1
    assert result.items[0].document_id == personal_document_id
    assert result.items[0].project_id is None
    assert outcome.sources == ()
    assert capabilities.research_search.candidate_page.call_args.kwargs["scope"] == (
        ResearchSearchScope.personal_library()
    )
    capabilities.paper_collection_access.contains.assert_not_called()


def test_paper_search_includes_only_personal_and_selected_project_annotations() -> None:
    document_id = uuid4()
    selected_project_id = uuid4()
    threads = [
        _thread(document_id=document_id, project_id=None),
        _thread(document_id=document_id, project_id=selected_project_id),
    ]
    capabilities = _capabilities(threads)

    outcome = _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput(
            query="compression",
            scope=PaperKnowledgeScope(
                document_id=document_id,
                project_id=selected_project_id,
            ),
            kinds=["annotation_thread"],
        ),
    )
    result = KnowledgeSearchOutput.model_validate(outcome.payload)

    assert {item.project_id for item in result.items} == {
        None,
        selected_project_id,
    }
    assert capabilities.research_search.candidate_page.call_args.kwargs["scope"] == (
        ResearchSearchScope.paper(
            document_id,
            project_id=selected_project_id,
        )
    )


def test_knowledge_search_shares_equal_family_source_windows_per_request() -> None:
    capabilities = _capabilities([])
    handler = _handler()

    handler.search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput(
            query="compression",
            scope=AllAccessibleKnowledgeScope(),
            kinds=[
                "paper",
                "paper_passage",
                "annotation_thread",
                "annotation_comment",
            ],
        ),
    )

    capabilities.paper_search.candidate_page.assert_called_once()
    capabilities.research_search.candidate_page.assert_called_once()


def test_knowledge_search_queries_diverged_family_positions_independently() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    handler = _handler()
    context = _context()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=[
            "paper",
            "paper_passage",
            "annotation_thread",
            "annotation_comment",
        ],
    )
    request = _request_with_cursor_state(
        handler=handler,
        context=context,
        request=request,
        state=KnowledgeSearchCursorState(
            paper=KnowledgeProducerPosition(offset=2),
            paper_passage=KnowledgeProducerPosition(offset=3),
            annotation_thread=KnowledgeProducerPosition(
                offset=2,
                anchor_key=now.isoformat(),
                anchor_id=UUID(int=71),
            ),
            annotation_comment=KnowledgeProducerPosition(
                offset=3,
                anchor_key=(now - timedelta(seconds=1)).isoformat(),
                anchor_id=UUID(int=72),
            ),
        ),
    )
    capabilities = _capabilities([])

    handler.search_knowledge(capabilities, context, request)

    assert capabilities.paper_search.candidate_page.call_count == 2
    assert {
        call.kwargs["offset"]
        for call in capabilities.paper_search.candidate_page.call_args_list
    } == {2, 3}
    assert capabilities.research_search.candidate_page.call_count == 2
    assert {
        cast(ResearchSearchPosition, call.kwargs["after"]).item_id
        for call in capabilities.research_search.candidate_page.call_args_list
    } == {UUID(int=71), UUID(int=72)}


def test_knowledge_search_does_not_query_an_exhausted_sibling() -> None:
    handler = _handler()
    context = _context()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=[
            "paper",
            "paper_passage",
            "annotation_thread",
            "annotation_comment",
        ],
    )
    request = _request_with_cursor_state(
        handler=handler,
        context=context,
        request=request,
        state=KnowledgeSearchCursorState(
            paper=KnowledgeProducerPosition(exhausted=True),
            annotation_thread=KnowledgeProducerPosition(exhausted=True),
        ),
    )
    capabilities = _capabilities([])

    handler.search_knowledge(capabilities, context, request)

    capabilities.paper_search.candidate_page.assert_called_once()
    assert capabilities.paper_search.candidate_page.call_args.kwargs["offset"] == 0
    capabilities.research_search.candidate_page.assert_called_once()
    assert capabilities.research_search.candidate_page.call_args.kwargs["after"] is None


@pytest.mark.parametrize(
    ("kind", "paper_calls", "annotation_calls"),
    [
        ("paper", 1, 0),
        ("paper_passage", 1, 0),
        ("annotation_thread", 0, 1),
        ("annotation_comment", 0, 1),
    ],
)
def test_knowledge_search_single_kind_queries_only_its_family(
    kind: str,
    paper_calls: int,
    annotation_calls: int,
) -> None:
    capabilities = _capabilities([])

    _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput.model_validate(
            {
                "query": "compression",
                "scope": {"kind": "all_accessible"},
                "kinds": [kind],
            }
        ),
    )

    assert capabilities.paper_search.candidate_page.call_count == paper_calls
    assert capabilities.research_search.candidate_page.call_count == annotation_calls


def test_knowledge_search_max_page_fits_the_complete_mcp_result_budget() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    escape_heavy = '\x00"\\😀' * 1_200
    capabilities = _capabilities([])
    hostile_results = [
        PaperSearchResult(
            document_id=uuid4(),
            title=escape_heavy,
            authors=[],
            abstract=escape_heavy,
            status="ready",
            publish_date=None,
            created_at=now,
            last_accessed_at=now,
            snippets=[PaperSearchSnippet(text=escape_heavy)],
        )
        for _ in range(100)
    ]
    capabilities.paper_search.candidate_page.return_value = _paper_candidate_page(
        hostile_results[:25],
        total=100,
    )

    outcome = _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput(
            query="compression",
            scope=LibraryKnowledgeScope(),
            kinds=["paper_passage"],
            limit=100,
        ),
    )
    result = KnowledgeSearchOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert len(result.items) == KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS
    assert result.next_cursor is not None
    assert len(outcome.sources) == KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES


def test_library_search_uses_exact_personal_library_output_scope() -> None:
    personal_document_id = uuid4()
    capabilities = _capabilities([])
    capabilities.research_output_catalog.candidate_page.return_value = _output_page(
        [_output_summary(document_id=personal_document_id)]
    )

    outcome = _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput(
            query="compression",
            scope=LibraryKnowledgeScope(),
            kinds=["research_output"],
        ),
    )
    result = KnowledgeSearchOutput.model_validate(outcome.payload)

    assert [item.document_id for item in result.items] == [personal_document_id]
    assert (
        capabilities.research_output_catalog.candidate_page.call_args.kwargs["scope"]
        == ResearchOutputCatalogScope.personal_library()
    )
    capabilities.paper_library.list_outputs.assert_not_called()
    capabilities.research_items.list_document.assert_not_called()


@pytest.mark.parametrize(
    ("scope", "expected_scope"),
    [
        (LibraryKnowledgeScope(), ResearchOutputCatalogScope.personal_library()),
        (AllAccessibleKnowledgeScope(), ResearchOutputCatalogScope.library()),
        (
            ProjectKnowledgeScope(project_id=UUID(int=101)),
            ResearchOutputCatalogScope.project(UUID(int=101)),
        ),
        (
            PaperKnowledgeScope(document_id=UUID(int=202), project_id=UUID(int=303)),
            ResearchOutputCatalogScope.paper(UUID(int=202), project_id=UUID(int=303)),
        ),
    ],
)
def test_research_output_search_uses_only_bounded_sql_summaries(
    scope: object,
    expected_scope: ResearchOutputCatalogScope,
) -> None:
    hostile = '\x00"\\😀' * 240
    capabilities = _capabilities([])
    capabilities.research_output_catalog.candidate_page.return_value = _output_page(
        [_output_summary(text=hostile) for _ in range(25)],
        has_more=True,
    )

    outcome = _handler().search_knowledge(
        capabilities,
        _context(),
        SearchKnowledgeInput.model_validate(
            {
                "query": "compression",
                "scope": scope,
                "kinds": ["research_output"],
                "limit": 100,
            }
        ),
    )
    result = KnowledgeSearchOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert len(result.items) == KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS
    call = capabilities.research_output_catalog.candidate_page.call_args.kwargs
    assert call["scope"] == expected_scope
    assert call["limit"] == KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT
    assert call["query"] == "compression"
    assert call["kinds"] == (
        ResearchItemKind.CITATION,
        ResearchItemKind.AUDIO_OVERVIEW,
        ResearchItemKind.DATA_TABLE,
    )
    capabilities.paper_search.candidate_page.assert_not_called()
    capabilities.research_search.candidate_page.assert_not_called()
    capabilities.paper_library.list_outputs.assert_not_called()
    capabilities.projects.outputs.assert_not_called()
    capabilities.research_items.list_document.assert_not_called()
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES


def test_research_output_candidate_pagination_is_stable() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    item_ids = [UUID(int=index + 1) for index in range(25)]
    capabilities = _capabilities([])
    outputs = [
        _output_summary(
            item_id=item_id,
            updated_at=now.replace(minute=25 - index),
        )
        for index, item_id in enumerate(item_ids)
    ]

    def candidate_page(**kwargs: object) -> ResearchOutputSummaryPage:
        after = kwargs["after"]
        offset = (
            0
            if after is None
            else item_ids.index(cast(ResearchOutputPagePosition, after).item_id) + 1
        )
        page = outputs[offset : offset + 25]
        return _output_page(page, has_more=offset + len(page) < len(outputs))

    capabilities.research_output_catalog.candidate_page.side_effect = candidate_page
    handler = _handler()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=["research_output"],
        limit=10,
    )

    first = KnowledgeSearchOutput.model_validate(
        handler.search_knowledge(capabilities, _context(), request).payload
    )
    second = KnowledgeSearchOutput.model_validate(
        handler.search_knowledge(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": first.next_cursor}),
        ).payload
    )
    third = KnowledgeSearchOutput.model_validate(
        handler.search_knowledge(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": second.next_cursor}),
        ).payload
    )

    assert [item.entity_id for item in first.items + second.items + third.items] == (
        item_ids
    )
    assert first.next_cursor is not None
    assert second.next_cursor is not None
    assert third.next_cursor is None


def test_knowledge_search_continues_one_producer_beyond_three_windows() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    item_ids = [UUID(int=index + 1) for index in range(67)]
    outputs = [
        _output_summary(
            item_id=item_id,
            updated_at=now - timedelta(seconds=index),
        )
        for index, item_id in enumerate(item_ids)
    ]
    capabilities = _capabilities([])

    def candidate_page(**kwargs: object) -> ResearchOutputSummaryPage:
        after = cast(ResearchOutputPagePosition | None, kwargs["after"])
        limit = cast(int, kwargs["limit"])
        offset = 0 if after is None else item_ids.index(after.item_id) + 1
        items = outputs[offset : offset + limit]
        return _output_page(items, has_more=offset + len(items) < len(outputs))

    capabilities.research_output_catalog.candidate_page.side_effect = candidate_page
    handler = _handler()
    context = _context()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=["research_output"],
        limit=25,
    )

    pages: list[KnowledgeSearchOutput] = []
    while True:
        page = KnowledgeSearchOutput.model_validate(
            handler.search_knowledge(capabilities, context, request).payload
        )
        pages.append(page)
        if page.next_cursor is None:
            break
        assert len(page.next_cursor) <= 2_048
        request = request.model_copy(update={"cursor": page.next_cursor})

    returned = [item.entity_id for page in pages for item in page.items]
    assert [len(page.items) for page in pages] == [25, 25, 17]
    assert returned == item_ids
    assert len(returned) == len(set(returned))
    assert pages[-1].next_cursor is None


def test_knowledge_search_continues_flattened_passages_without_loss() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    papers = [
        PaperSearchResult(
            document_id=UUID(int=10_000 + paper_index),
            title=f"Paper {paper_index}",
            authors=[],
            abstract="compression evidence",
            status="ready",
            publish_date=None,
            created_at=now - timedelta(seconds=paper_index),
            last_accessed_at=now - timedelta(seconds=paper_index),
            snippets=[
                PaperSearchSnippet(
                    text=f"passage {paper_index}:{child_index}",
                    start_line=paper_index * 3 + child_index + 1,
                    end_line=paper_index * 3 + child_index + 1,
                )
                for child_index in range(3)
            ],
        )
        for paper_index in range(21)
    ]
    capabilities = _capabilities([])

    def paper_page(**kwargs: object) -> PaperSearchCandidatePage:
        offset = cast(int, kwargs["offset"])
        limit = cast(PaperSearchRequest, kwargs["request"]).limit
        return _paper_candidate_page(
            papers[offset : offset + limit],
            total=len(papers),
        )

    capabilities.paper_search.candidate_page.side_effect = paper_page
    handler = _handler()
    request = SearchKnowledgeInput(
        query="compression",
        scope=LibraryKnowledgeScope(),
        kinds=["paper_passage"],
        limit=25,
    )

    returned: list[tuple[UUID, int]] = []
    page_sizes: list[int] = []
    while True:
        page = KnowledgeSearchOutput.model_validate(
            handler.search_knowledge(capabilities, _context(), request).payload
        )
        page_sizes.append(len(page.items))
        returned.extend(
            (
                cast(UUID, item.document_id),
                cast(int, cast(dict[str, object], item.locator)["start_line"]),
            )
            for item in page.items
        )
        if page.next_cursor is None:
            break
        request = request.model_copy(update={"cursor": page.next_cursor})

    expected = [
        (paper.document_id, paper_index * 3 + child_index + 1)
        for paper_index, paper in enumerate(papers)
        for child_index in range(3)
    ]
    assert page_sizes == [25, 25, 13]
    assert returned == expected
    assert len(returned) == len(set(returned)) == 63


def test_knowledge_search_continues_flattened_comments_by_thread_keyset() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    threads = [
        ResearchSearchResult(
            id=UUID(int=20_000 + thread_index),
            document_id=UUID(int=30_000 + thread_index),
            project_id=None,
            document_title=f"Thread {thread_index}",
            quote_text="compression annotation",
            position=None,
            role="assistant",
            created_at=now - timedelta(seconds=thread_index),
            matching_comments=[
                ResearchSearchComment(
                    id=UUID(int=40_000 + thread_index * 3 + child_index),
                    content=f"comment {thread_index}:{child_index}",
                    role="user",
                    created_at=now
                    - timedelta(seconds=thread_index, microseconds=child_index),
                )
                for child_index in range(3)
            ],
        )
        for thread_index in range(21)
    ]
    capabilities = _capabilities([])

    def thread_page(**kwargs: object) -> ResearchSearchCandidatePage:
        after = cast(ResearchSearchPosition | None, kwargs["after"])
        limit = cast(int, kwargs["limit"])
        offset = (
            0
            if after is None
            else next(
                index + 1
                for index, thread in enumerate(threads)
                if thread.id == after.item_id
            )
        )
        items = threads[offset : offset + limit]
        return ResearchSearchCandidatePage(
            items=tuple(items),
            has_more=offset + len(items) < len(threads),
        )

    capabilities.research_search.candidate_page.side_effect = thread_page
    handler = _handler()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=["annotation_comment"],
        limit=25,
    )

    returned: list[UUID] = []
    page_sizes: list[int] = []
    while True:
        page = KnowledgeSearchOutput.model_validate(
            handler.search_knowledge(capabilities, _context(), request).payload
        )
        page_sizes.append(len(page.items))
        returned.extend(item.entity_id for item in page.items)
        if page.next_cursor is None:
            break
        request = request.model_copy(update={"cursor": page.next_cursor})

    expected = [
        comment.id for thread in threads for comment in thread.matching_comments
    ]
    assert page_sizes == [25, 25, 13]
    assert returned == expected
    assert len(returned) == len(set(returned)) == 63


def test_knowledge_search_mixed_producers_have_no_gaps_or_duplicates() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    paper_ids = [UUID(int=1_000 + index) for index in range(31)]
    papers = [
        PaperSearchResult(
            document_id=document_id,
            title=f"Paper {index}",
            authors=[],
            abstract="compression evidence",
            status="ready",
            publish_date=None,
            created_at=now - timedelta(seconds=index),
            last_accessed_at=now - timedelta(seconds=index),
            snippets=[],
        )
        for index, document_id in enumerate(paper_ids)
    ]
    threads = [
        ResearchSearchResult(
            id=UUID(int=2_000 + index),
            document_id=UUID(int=3_000 + index),
            project_id=None,
            document_title=f"Thread paper {index}",
            quote_text="compression annotation",
            position=None,
            role="assistant",
            created_at=now - timedelta(seconds=index),
            matching_comments=[],
        )
        for index in range(31)
    ]
    output_ids = [UUID(int=4_000 + index) for index in range(31)]
    outputs = [
        _output_summary(
            item_id=item_id,
            updated_at=now - timedelta(seconds=index),
        )
        for index, item_id in enumerate(output_ids)
    ]
    capabilities = _capabilities([])

    def paper_page(**kwargs: object) -> PaperSearchCandidatePage:
        offset = cast(int, kwargs["offset"])
        limit = cast(PaperSearchRequest, kwargs["request"]).limit
        return _paper_candidate_page(
            papers[offset : offset + limit],
            total=len(papers),
        )

    def thread_page(**kwargs: object) -> ResearchSearchCandidatePage:
        after = cast(ResearchSearchPosition | None, kwargs["after"])
        limit = cast(int, kwargs["limit"])
        offset = (
            0
            if after is None
            else next(
                index + 1
                for index, thread in enumerate(threads)
                if thread.id == after.item_id
            )
        )
        items = threads[offset : offset + limit]
        return ResearchSearchCandidatePage(
            items=tuple(items),
            has_more=offset + len(items) < len(threads),
        )

    def output_page(**kwargs: object) -> ResearchOutputSummaryPage:
        after = cast(ResearchOutputPagePosition | None, kwargs["after"])
        limit = cast(int, kwargs["limit"])
        offset = 0 if after is None else output_ids.index(after.item_id) + 1
        items = outputs[offset : offset + limit]
        return _output_page(items, has_more=offset + len(items) < len(outputs))

    capabilities.paper_search.candidate_page.side_effect = paper_page
    capabilities.research_search.candidate_page.side_effect = thread_page
    capabilities.research_output_catalog.candidate_page.side_effect = output_page
    handler = _handler()
    context = _context()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=["paper", "annotation_thread", "research_output"],
        limit=17,
    )

    returned: list[tuple[str, UUID]] = []
    cursors: list[str] = []
    for _ in range(10):
        page = KnowledgeSearchOutput.model_validate(
            handler.search_knowledge(capabilities, context, request).payload
        )
        returned.extend((item.kind, item.entity_id) for item in page.items)
        if page.next_cursor is None:
            break
        cursors.append(page.next_cursor)
        request = request.model_copy(update={"cursor": page.next_cursor})
    else:  # pragma: no cover - protects the test from a non-progressing cursor
        raise AssertionError("knowledge search did not reach its terminal page")

    expected = {
        *(("paper", item_id) for item_id in paper_ids),
        *(("annotation_thread", thread.id) for thread in threads),
        *(("research_output", item_id) for item_id in output_ids),
    }
    assert set(returned) == expected
    assert len(returned) == len(expected) == 93
    assert len(returned) == len(set(returned))
    assert len(cursors) >= 3


def test_knowledge_cursor_binds_signature_actor_and_request() -> None:
    item = _output_summary(item_id=UUID(int=50_000))
    capabilities = _capabilities([])
    capabilities.research_output_catalog.candidate_page.return_value = _output_page(
        [item],
        has_more=True,
    )
    handler = _handler()
    context = _context()
    request = SearchKnowledgeInput(
        query="compression",
        scope=AllAccessibleKnowledgeScope(),
        kinds=["research_output"],
        limit=10,
    )
    first = KnowledgeSearchOutput.model_validate(
        handler.search_knowledge(capabilities, context, request).payload
    )
    assert first.next_cursor is not None
    cursor = first.next_cursor

    changed_requests = [
        request.model_copy(update={"query": "different query", "cursor": cursor}),
        request.model_copy(update={"limit": 9, "cursor": cursor}),
        request.model_copy(
            update={
                "filters": PaperSearchFilters(published_from=datetime(2025, 1, 1)),
                "cursor": cursor,
            }
        ),
    ]
    for changed in changed_requests:
        with pytest.raises(AppError) as raised:
            handler.search_knowledge(capabilities, context, changed)
        assert raised.value.code == "knowledge_search_cursor_invalid"

    other_context = replace(
        context,
        actor=context.actor.model_copy(update={"id": 8}),
    )
    with pytest.raises(AppError) as raised:
        handler.search_knowledge(
            capabilities,
            other_context,
            request.model_copy(update={"cursor": cursor}),
        )
    assert raised.value.code == "knowledge_search_cursor_invalid"

    tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
    with pytest.raises(AppError) as raised:
        handler.search_knowledge(
            capabilities,
            context,
            request.model_copy(update={"cursor": tampered}),
        )
    assert raised.value.code == "knowledge_search_cursor_invalid"


def test_annotation_thread_tool_uses_a_filter_bound_cursor() -> None:
    document_id = uuid4()
    capabilities = MagicMock()
    summaries = [_annotation_summary(document_id) for _ in range(3)]
    keyset = AnnotationThreadSummaryKeyset(
        page_number=2,
        anchor_y=0.25,
        anchor_x=0.5,
        start_offset=None,
        end_offset=None,
        created_at=summaries[1].created_at,
        item_id=summaries[1].id,
    )
    capabilities.research_items.list_annotation_thread_summaries_page.side_effect = (
        AnnotationThreadSummaryPage(
            items=summaries[:2],
            next_keyset=keyset,
        ),
        AnnotationThreadSummaryPage(
            items=summaries[2:],
            next_keyset=None,
        ),
    )
    handler = _handler()
    request = ListAnnotationThreadsInput(document_id=document_id, limit=2)

    first = handler.list_annotation_threads(capabilities, _context(), request)
    first_page = ThreadListOutput.model_validate(first.payload)
    assert [item.id for item in first_page.items] == [
        summaries[0].id,
        summaries[1].id,
    ]
    assert first_page.next_cursor is not None
    assert len(first.resource_links) == 2

    second = handler.list_annotation_threads(
        capabilities,
        _context(),
        request.model_copy(update={"cursor": first_page.next_cursor}),
    )
    second_page = ThreadListOutput.model_validate(second.payload)
    assert [item.id for item in second_page.items] == [summaries[2].id]
    assert second_page.next_cursor is None
    assert (
        capabilities.research_items.list_annotation_thread_summaries_page.call_args_list[
            1
        ].kwargs["after"]
        == keyset
    )
