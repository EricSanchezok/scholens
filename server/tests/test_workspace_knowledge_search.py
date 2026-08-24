from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperSearchResponse,
)
from app.modules.papers.application.contracts.documents import (
    LibraryOutputListResponse,
    LibraryOutputResponse,
    LibraryOutputSourceResponse,
)
from app.modules.research.application.contracts import (
    AnnotationThreadCapabilities,
    AnnotationThreadListResponse,
    AnnotationThreadSummaryResponse,
    DataTableContent,
    DocumentResearchAudience,
    PersonalResearchAudience,
    ProjectResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
)
from app.modules.research.application.search import (
    ResearchSearchResponse,
    ResearchSearchResult,
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
    ResearchAudienceType,
    ResearchItemKind,
)
from app.tooling.contracts import ToolExecutionContext
from app.tooling.workspace_contracts import (
    KnowledgeSearchOutput,
    LibraryKnowledgeScope,
    ListAnnotationThreadsInput,
    PaperKnowledgeScope,
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
    capabilities.paper_search.return_value = PaperSearchResponse(items=[], total=0)
    capabilities.research_search.return_value = ResearchSearchResponse(
        items=threads,
        total=len(threads),
    )
    return capabilities


def _output(
    *,
    audience_type: ResearchAudienceType,
    audience_id: UUID | None,
) -> LibraryOutputResponse:
    if audience_type is ResearchAudienceType.PERSONAL:
        audience = PersonalResearchAudience()
    elif audience_type is ResearchAudienceType.DOCUMENT:
        assert audience_id is not None
        audience = DocumentResearchAudience(document_id=audience_id)
    else:
        assert audience_id is not None
        audience = ProjectResearchAudience(project_id=audience_id)
    now = datetime(2026, 8, 16, tzinfo=UTC)
    return LibraryOutputResponse(
        item=ResearchItemResponse(
            id=uuid4(),
            kind=ResearchItemKind.DATA_TABLE,
            audience=audience,
            target_document_id=(
                audience_id if audience_type is ResearchAudienceType.DOCUMENT else None
            ),
            created_by=ResearchCreatorResponse(id=7, display_name="Researcher"),
            created_at=now,
            updated_at=now,
            capabilities=ResearchItemCapabilities(edit=True, delete=True),
            data_table=DataTableContent(
                title="Compression comparison",
                columns=[],
                rows=[],
                citations=[],
                row_failures=[],
            ),
        ),
        title="Compression comparison",
        source=LibraryOutputSourceResponse(
            audience_type=audience_type,
            audience_id=audience_id,
            title="Source",
        ),
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


def test_library_search_excludes_project_and_project_only_annotations() -> None:
    personal_document_id = uuid4()
    project_only_document_id = uuid4()
    capabilities = _capabilities(
        [
            _thread(document_id=personal_document_id, project_id=None),
            _thread(document_id=project_only_document_id, project_id=None),
            _thread(document_id=personal_document_id, project_id=uuid4()),
        ]
    )
    capabilities.paper_collection_access.contains.side_effect = lambda **values: (
        values["document_id"] == personal_document_id
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


def test_paper_search_includes_only_personal_and_selected_project_annotations() -> None:
    document_id = uuid4()
    selected_project_id = uuid4()
    threads = [
        _thread(document_id=document_id, project_id=None),
        _thread(document_id=document_id, project_id=selected_project_id),
        _thread(document_id=document_id, project_id=uuid4()),
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


def test_library_search_excludes_project_and_project_only_document_outputs() -> None:
    personal_document_id = uuid4()
    project_only_document_id = uuid4()
    capabilities = _capabilities([])
    capabilities.paper_library.list_outputs.return_value = LibraryOutputListResponse(
        items=[
            _output(audience_type=ResearchAudienceType.PERSONAL, audience_id=None),
            _output(
                audience_type=ResearchAudienceType.DOCUMENT,
                audience_id=personal_document_id,
            ),
            _output(
                audience_type=ResearchAudienceType.DOCUMENT,
                audience_id=project_only_document_id,
            ),
            _output(
                audience_type=ResearchAudienceType.PROJECT,
                audience_id=uuid4(),
            ),
        ],
        total_count=4,
    )
    capabilities.paper_collection_access.contains.side_effect = lambda **values: (
        values["document_id"] == personal_document_id
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

    assert len(result.items) == 2
    assert {item.document_id for item in result.items} == {
        None,
        personal_document_id,
    }


def test_annotation_thread_tool_uses_a_filter_bound_cursor() -> None:
    document_id = uuid4()
    capabilities = MagicMock()
    summaries = [_annotation_summary(document_id) for _ in range(3)]
    capabilities.research_items.list_annotation_threads.return_value = (
        AnnotationThreadListResponse(items=summaries)
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
