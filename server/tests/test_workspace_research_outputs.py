from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import jsonschema
import pytest
from app.modules.papers.application.contracts.citation import CitationData
from app.modules.papers.application.contracts.documents import (
    LibraryOutputListResponse,
    LibraryOutputResponse,
    LibraryOutputSourceResponse,
    LibraryOutputSort,
)
from app.modules.projects.application.contracts import ProjectOutputListResponse
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadCapabilities,
    AnnotationThreadContent,
    AudioOverviewContent,
    CitationContent,
    CitationSnapshot,
    DataTableContent,
    DocumentResearchAudience,
    PersonalResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
    ResearchOutputCreatorSummary,
    ResearchOutputSourceSummary,
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.positions import ParsedTextPosition
from app.modules.research.application.catalog import (
    ResearchOutputCatalogScope,
    ResearchOutputCatalogSort,
)
from app.modules.research.application.items import (
    LegacyResearchDocumentPage,
    ResearchItemPageAccess,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from app.tooling.contracts import DEFAULT_TOOL_OUTPUT_BYTES, ToolExecutionContext
from app.tooling.annotation_mutation_projection import (
    ANNOTATION_MUTATION_IDENTITY_JSON_BYTES,
)
from app.tooling.results import serialize_tool_success
from app.tooling.workspace_contracts import (
    AnnotationThreadInput,
    CommentActionOutput,
    LibraryOutputScope,
    ListResearchOutputSummariesInput,
    ListResearchOutputsInput,
    PaperOutputScope,
    ProjectOutputScope,
    ResearchOutputInput,
    ResearchOutputList,
    ResearchOutputSummaryListToolResponse,
    ResearchItemToolResponse,
    ThreadActionOutput,
    UpdateAnnotationCommentInput,
    UpdateAnnotationThreadInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers
from pydantic import BaseModel, ValidationError


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _context(user_id: int = 7) -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(user_id),
        operation=operation,
        paper_collection=MagicMock(),
        anchor_document_id=None,
        invocation_id="research-output-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="research-output-test-secret",
    )


def _research_item(
    *,
    kind: ResearchItemKind,
    document_id: UUID,
    title: str,
    updated_at: datetime,
) -> ResearchItemResponse:
    common: dict[str, object] = {
        "id": uuid4(),
        "kind": kind,
        "audience": (
            PersonalResearchAudience()
            if kind is ResearchItemKind.ANNOTATION_THREAD
            else DocumentResearchAudience(document_id=document_id)
        ),
        "target_document_id": document_id,
        "created_by": ResearchCreatorResponse(id=7, display_name="Researcher"),
        "created_at": updated_at - timedelta(minutes=1),
        "updated_at": updated_at,
        "capabilities": ResearchItemCapabilities(edit=True, delete=True),
    }
    if kind is ResearchItemKind.ANNOTATION_THREAD:
        return ResearchItemResponse(
            **common,
            annotation_thread=AnnotationThreadContent(
                quote_text=title,
                position=None,
                color=AnnotationColor.YELLOW,
                role="assistant",
                mode=AnnotationThreadMode.HIGHLIGHT,
                comment_count=0,
                last_activity_at=updated_at,
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
            ),
        )
    if kind is ResearchItemKind.CITATION:
        return ResearchItemResponse(
            **common,
            citation=CitationContent(
                snapshot=CitationSnapshot(
                    kind="citation",
                    document_id=str(document_id),
                    preferred_style="APA",
                    style_display="APA 7th Edition",
                    data=CitationData(document_id=str(document_id), title=title),
                    method="cached",
                )
            ),
        )
    if kind is ResearchItemKind.AUDIO_OVERVIEW:
        return ResearchItemResponse(
            **common,
            audio_overview=AudioOverviewContent(
                title=title,
                transcript="Overview transcript",
                citations=[],
                audio_url="https://scholens.example/audio.mp3",
                voice_id="voice",
                model_version="v1",
            ),
        )
    return ResearchItemResponse(
        **common,
        data_table=DataTableContent(
            title=title,
            columns=[],
            rows=[],
            citations=[],
            row_failures=[],
        ),
    )


def _research_summary(
    *,
    kind: ResearchItemKind,
    document_id: UUID,
    title: str,
    updated_at: datetime,
    item_id: UUID | None = None,
) -> ResearchOutputSummary:
    item_id = item_id or uuid4()
    audience = (
        PersonalResearchAudience()
        if kind is ResearchItemKind.ANNOTATION_THREAD
        else DocumentResearchAudience(document_id=document_id)
    )
    audience_type = (
        ResearchAudienceType.PERSONAL
        if kind is ResearchItemKind.ANNOTATION_THREAD
        else ResearchAudienceType.DOCUMENT
    )
    resource_kind = (
        "annotation-threads"
        if kind is ResearchItemKind.ANNOTATION_THREAD
        else "research-outputs"
    )
    return ResearchOutputSummary(
        item_id=item_id,
        kind=kind,
        audience=audience,
        target_document_id=document_id,
        title=title,
        excerpt=f"{title} excerpt",
        creator=ResearchOutputCreatorSummary(id=7, display_name="Researcher"),
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
        source=ResearchOutputSourceSummary(
            audience_type=audience_type,
            audience_id=(
                document_id if audience_type is ResearchAudienceType.DOCUMENT else None
            ),
            title=(
                "Paper"
                if audience_type is ResearchAudienceType.DOCUMENT
                else "Personal Library"
            ),
        ),
        resource_uri=f"scholens://{resource_kind}/{item_id}",
    )


def _library_output(item: ResearchItemResponse) -> LibraryOutputResponse:
    audience_type = (
        ResearchAudienceType.PERSONAL
        if item.kind is ResearchItemKind.ANNOTATION_THREAD
        else ResearchAudienceType.DOCUMENT
    )
    return LibraryOutputResponse(
        item=item,
        title=item.kind.value,
        source=LibraryOutputSourceResponse(
            audience_type=audience_type,
            audience_id=(
                item.target_document_id
                if audience_type is ResearchAudienceType.DOCUMENT
                else None
            ),
            title=(
                "Paper"
                if audience_type is ResearchAudienceType.DOCUMENT
                else "Personal Library"
            ),
        ),
    )


def _legacy_access(
    item: ResearchItemResponse,
    *,
    revision: str = "a" * 64,
    payload_upper_bound: int = 4_096,
) -> ResearchItemPageAccess:
    return ResearchItemPageAccess(
        item_id=item.id,
        kind=item.kind,
        revision=revision,
        durable_json_utf8_upper_bound=payload_upper_bound,
        legacy_payload_json_utf8_upper_bound=payload_upper_bound,
    )


def test_summary_catalog_pages_all_four_kinds_with_resource_closure() -> None:
    document_id = uuid4()
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    items = [
        _research_summary(
            kind=kind,
            document_id=document_id,
            title=kind.value,
            updated_at=now + timedelta(minutes=index),
        )
        for index, kind in enumerate(ResearchItemKind)
    ]
    capabilities = MagicMock()
    capabilities.research_output_catalog.list.return_value = (
        ResearchOutputSummaryListResponse(
            items=items,
            total_count=4,
        )
    )
    handler = _handler()
    request = ListResearchOutputSummariesInput(
        scope=PaperOutputScope(document_id=document_id),
        sort=LibraryOutputSort.TITLE_ASC,
        limit=4,
    )

    result = handler.list_research_output_summaries(capabilities, _context(), request)
    page = ResearchOutputSummaryListToolResponse.model_validate(result.payload)
    assert [item.kind for item in page.items] == list(ResearchItemKind)
    assert page.total_count == 4
    assert all(
        item.reader_url == f"https://scholens.example/reader/{document_id}"
        for item in page.items
    )
    assert [link.uri for link in result.resource_links] == [
        item.resource_uri for item in items
    ]
    call = capabilities.research_output_catalog.list.call_args.kwargs
    assert call["scope"] == ResearchOutputCatalogScope.paper(document_id)
    assert call["sort"] is ResearchOutputCatalogSort.TITLE_ASC
    capabilities.research_items.list_document.assert_not_called()


def test_legacy_and_summary_list_contracts_expose_all_four_kinds() -> None:
    legacy_schema = ListResearchOutputsInput.model_json_schema()
    summary_schema = ListResearchOutputSummariesInput.model_json_schema()

    assert ListResearchOutputsInput(scope=LibraryOutputScope()).kinds == []
    assert legacy_schema["properties"]["kinds"]["maxItems"] == 4
    assert legacy_schema["properties"]["limit"]["maximum"] == 100
    assert summary_schema["properties"]["limit"]["maximum"] == 25
    assert legacy_schema["$defs"]["ResearchItemKind"]["enum"] == [
        "annotation_thread",
        "citation",
        "audio_overview",
        "data_table",
    ]


def test_legacy_library_list_uses_its_historical_gateway_and_wrapper() -> None:
    document_id = uuid4()
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    full_items = [
        _research_item(
            kind=kind,
            document_id=document_id,
            title=kind.value,
            updated_at=now + timedelta(minutes=index),
        )
        for index, kind in enumerate(ResearchItemKind)
    ]
    wrapped = [_library_output(item) for item in full_items]
    capabilities = MagicMock()
    capabilities.paper_library.list_outputs.return_value = LibraryOutputListResponse(
        items=wrapped,
        next_cursor="legacy-library-next",
        total_count=8,
    )

    listed = _handler().list_research_outputs(
        capabilities,
        _context(),
        ListResearchOutputsInput(
            scope=LibraryOutputScope(),
            query="Source title",
            sort=LibraryOutputSort.TITLE_DESC,
            cursor="merge-base-library-cursor",
            limit=100,
        ),
    )
    legacy_page = ResearchOutputList.model_validate(listed.payload)

    listed_items = [
        LibraryOutputResponse.model_validate(item) for item in legacy_page.items
    ]
    assert [entry.item.kind for entry in listed_items] == list(ResearchItemKind)
    assert legacy_page.next_cursor == "legacy-library-next"
    assert legacy_page.total_count == 8
    call = capabilities.paper_library.list_outputs.call_args.kwargs
    assert call["query"] == "Source title"
    assert call["sort"] is LibraryOutputSort.TITLE_DESC
    assert call["cursor"] == "merge-base-library-cursor"
    assert call["limit"] == 100
    assert call["kinds"] == ()
    assert call["maximum_payload_json_bytes"] > 0
    capabilities.research_output_catalog.list.assert_not_called()
    capabilities.projects.outputs.assert_not_called()
    capabilities.research_items.list_document_legacy.assert_not_called()


def test_legacy_list_explicit_annotation_filter_returns_full_thread() -> None:
    document_id = uuid4()
    annotation = _research_item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=document_id,
        title="Annotation output",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.paper_library.list_outputs.return_value = LibraryOutputListResponse(
        items=[_library_output(annotation)],
        total_count=1,
    )

    result = _handler().list_research_outputs(
        capabilities,
        _context(),
        ListResearchOutputsInput(
            scope=LibraryOutputScope(),
            kinds=[ResearchItemKind.ANNOTATION_THREAD],
        ),
    )

    page = ResearchOutputList.model_validate(result.payload)
    assert LibraryOutputResponse.model_validate(page.items[0]).item == annotation
    assert capabilities.paper_library.list_outputs.call_args.kwargs["kinds"] == (
        ResearchItemKind.ANNOTATION_THREAD,
    )
    capabilities.research_output_catalog.list.assert_not_called()


def test_legacy_list_keeps_its_one_hundred_item_contract() -> None:
    document_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    full_items = [
        _research_item(
            kind=ResearchItemKind.CITATION,
            document_id=document_id,
            title=f"Citation {index}",
            updated_at=now + timedelta(minutes=index),
        )
        for index in range(30)
    ]
    capabilities = MagicMock()
    capabilities.paper_library.list_outputs.return_value = LibraryOutputListResponse(
        items=[_library_output(item) for item in full_items],
        total_count=30,
    )

    page = ResearchOutputList.model_validate(
        _handler()
        .list_research_outputs(
            capabilities,
            _context(),
            ListResearchOutputsInput(scope=LibraryOutputScope(), limit=100),
        )
        .payload
    )

    assert len(page.items) == 30
    assert page.total_count == 30
    capabilities.paper_library.list_outputs.assert_called_once()
    call = capabilities.paper_library.list_outputs.call_args
    assert call.kwargs["limit"] == 100
    assert call.kwargs["cursor"] is None
    capabilities.research_output_catalog.list.assert_not_called()
    assert (
        serialize_tool_success(
            _handler().list_research_outputs(
                capabilities,
                _context(),
                ListResearchOutputsInput(scope=LibraryOutputScope(), limit=100),
            )
        ).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_legacy_project_and_paper_scopes_keep_their_historical_item_branches() -> None:
    document_id = uuid4()
    project_id = uuid4()
    citation = _research_item(
        kind=ResearchItemKind.CITATION,
        document_id=document_id,
        title="Cited paper",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.projects.outputs.return_value = ProjectOutputListResponse(
        items=[_library_output(citation)],
        total_count=1,
    )
    capabilities.research_items.list_document_legacy.return_value = (
        LegacyResearchDocumentPage(items=[citation], total_count=1)
    )
    handler = _handler()

    project_page = ResearchOutputList.model_validate(
        handler.list_research_outputs(
            capabilities,
            _context(),
            ListResearchOutputsInput(
                scope=ProjectOutputScope(project_id=project_id),
            ),
        ).payload
    )
    paper_page = ResearchOutputList.model_validate(
        handler.list_research_outputs(
            capabilities,
            _context(),
            ListResearchOutputsInput(
                scope=PaperOutputScope(document_id=document_id),
            ),
        ).payload
    )

    assert LibraryOutputResponse.model_validate(project_page.items[0]).item == citation
    paper_item = ResearchItemToolResponse.model_validate(paper_page.items[0])
    assert (
        ResearchItemResponse.model_validate(
            paper_item.model_dump(exclude={"reader_url"})
        )
        == citation
    )
    assert paper_item.reader_url == f"https://scholens.example/reader/{document_id}"
    capabilities.projects.outputs.assert_called_once()
    capabilities.paper_library.list_outputs.assert_not_called()
    capabilities.research_items.list_document.assert_not_called()
    capabilities.research_items.list_document_legacy.assert_called_once()
    capabilities.research_output_catalog.list.assert_not_called()


def test_paper_output_cursor_and_resized_limit_are_delegated_to_catalog() -> None:
    document_id = uuid4()
    capabilities = MagicMock()
    capabilities.research_output_catalog.list.return_value = (
        ResearchOutputSummaryListResponse(items=[], total_count=0)
    )
    handler = _handler()
    request = ListResearchOutputSummariesInput(
        scope=PaperOutputScope(document_id=document_id),
        cursor="opaque-keyset",
        limit=25,
    )

    handler.list_research_output_summaries(capabilities, _context(), request)

    call = capabilities.research_output_catalog.list.call_args.kwargs
    assert call["cursor"] == "opaque-keyset"
    assert call["limit"] == 25


@pytest.mark.parametrize(
    ("requested_kinds", "expected_kinds"),
    [
        ([], ()),
        (
            [ResearchItemKind.ANNOTATION_THREAD],
            (ResearchItemKind.ANNOTATION_THREAD,),
        ),
    ],
)
def test_library_outputs_accept_default_and_explicit_annotation_kind(
    requested_kinds: list[ResearchItemKind],
    expected_kinds: tuple[ResearchItemKind, ...],
) -> None:
    document_id = uuid4()
    annotation = _research_summary(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=document_id,
        title="Annotation output",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.research_output_catalog.list.return_value = (
        ResearchOutputSummaryListResponse(items=[annotation], total_count=1)
    )

    result = _handler().list_research_output_summaries(
        capabilities,
        _context(),
        ListResearchOutputSummariesInput(
            scope=LibraryOutputScope(),
            kinds=requested_kinds,
        ),
    )

    assert capabilities.research_output_catalog.list.call_args.kwargs["kinds"] == (
        expected_kinds
    )
    assert result.resource_links[0].uri == (
        f"scholens://annotation-threads/{annotation.item_id}"
    )
    capabilities.paper_library.list_outputs.assert_not_called()


def test_project_output_scope_maps_to_exact_catalog_project() -> None:
    project_id = uuid4()
    capabilities = MagicMock()
    capabilities.research_output_catalog.list.return_value = (
        ResearchOutputSummaryListResponse(items=[], total_count=0)
    )

    _handler().list_research_output_summaries(
        capabilities,
        _context(),
        ListResearchOutputSummariesInput(
            scope=ProjectOutputScope(project_id=project_id)
        ),
    )

    assert capabilities.research_output_catalog.list.call_args.kwargs["scope"] == (
        ResearchOutputCatalogScope.project(project_id)
    )


def test_get_research_output_accepts_annotation_and_links_its_thread_resource() -> None:
    document_id = uuid4()
    annotation = _research_item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=document_id,
        title="Annotation output",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    access = _legacy_access(annotation)
    capabilities.research_items.lock_legacy_read.return_value = access
    capabilities.research_items.authorize_page.return_value = access
    capabilities.research_items.get_item.return_value = annotation

    result = _handler().get_research_output(
        capabilities,
        _context(),
        ResearchOutputInput(item_id=annotation.id),
    )

    assert ResearchItemResponse.model_validate(result.payload) == annotation
    assert result.resource_links[0].uri == (
        f"scholens://annotation-threads/{annotation.id}"
    )


def test_get_annotation_thread_preflights_before_complete_hydration() -> None:
    annotation = _research_item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=uuid4(),
        title="Bounded discussion",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    access = _legacy_access(annotation)
    capabilities.research_items.lock_legacy_read.return_value = access
    capabilities.research_items.authorize_page.return_value = access
    capabilities.research_items.get_annotation_thread.return_value = annotation

    result = _handler().get_annotation_thread(
        capabilities,
        _context(),
        AnnotationThreadInput(thread_id=annotation.id),
    )

    assert ResearchItemResponse.model_validate(result.payload) == annotation
    capabilities.research_items.lock_legacy_read.assert_called_once()
    capabilities.research_items.get_annotation_thread.assert_called_once()


def test_get_annotation_thread_oversize_never_calls_complete_factory() -> None:
    annotation = _research_item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=uuid4(),
        title="Oversized discussion",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.research_items.lock_legacy_read.return_value = _legacy_access(
        annotation,
        payload_upper_bound=DEFAULT_TOOL_OUTPUT_BYTES,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_annotation_thread(
            capabilities,
            _context(),
            AnnotationThreadInput(thread_id=annotation.id),
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    assert raised.value.details["replacement_tool"] == "get_annotation_thread_page"
    capabilities.research_items.get_annotation_thread.assert_not_called()


def test_get_annotation_thread_detects_revision_change_after_hydration() -> None:
    annotation = _research_item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        document_id=uuid4(),
        title="Racing discussion",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.research_items.lock_legacy_read.return_value = _legacy_access(
        annotation,
        revision="a" * 64,
    )
    capabilities.research_items.get_annotation_thread.return_value = annotation
    capabilities.research_items.authorize_page.return_value = _legacy_access(
        annotation,
        revision="b" * 64,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_annotation_thread(
            capabilities,
            _context(),
            AnnotationThreadInput(thread_id=annotation.id),
        )

    assert raised.value.code == "research_output_snapshot_changed"


def test_get_research_output_rejects_budget_before_complete_hydration() -> None:
    document_id = uuid4()
    item = _research_item(
        kind=ResearchItemKind.DATA_TABLE,
        document_id=document_id,
        title="Oversized table",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.research_items.lock_legacy_read.return_value = _legacy_access(
        item,
        payload_upper_bound=DEFAULT_TOOL_OUTPUT_BYTES,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_research_output(
            capabilities,
            _context(),
            ResearchOutputInput(item_id=item.id),
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    assert raised.value.details["replacement_tool"] == "get_research_output_page"
    capabilities.research_items.get_item.assert_not_called()


def test_get_research_output_detects_revision_change_after_hydration() -> None:
    document_id = uuid4()
    item = _research_item(
        kind=ResearchItemKind.CITATION,
        document_id=document_id,
        title="Racing output",
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    capabilities = MagicMock()
    capabilities.research_items.lock_legacy_read.return_value = _legacy_access(
        item,
        revision="a" * 64,
    )
    capabilities.research_items.get_item.return_value = item
    capabilities.research_items.authorize_page.return_value = _legacy_access(
        item,
        revision="b" * 64,
    )

    with pytest.raises(AppError) as raised:
        _handler().get_research_output(
            capabilities,
            _context(),
            ResearchOutputInput(item_id=item.id),
        )

    assert raised.value.code == "research_output_snapshot_changed"


@pytest.mark.parametrize(
    ("model", "base"),
    [
        (UpdateAnnotationThreadRequest, {}),
        (UpdateAnnotationThreadInput, {"thread_id": str(uuid4())}),
    ],
)
def test_update_annotation_thread_schema_declares_exactly_one_non_null_change(
    model: type[BaseModel],
    base: dict[str, object],
) -> None:
    schema = model.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    valid_changes = [
        {"color": "yellow"},
        {"status": "resolved"},
        {"color": "yellow", "status": None},
        {"color": None, "status": "resolved"},
    ]
    invalid_changes = [
        {},
        {"color": None},
        {"status": None},
        {"color": "yellow", "status": "resolved"},
        {"color": None, "status": None},
    ]

    assert "oneOf" in schema
    assert all(validator.is_valid(base | change) for change in valid_changes)
    assert all(not validator.is_valid(base | change) for change in invalid_changes)


@pytest.mark.parametrize(
    "model, values",
    [
        (UpdateAnnotationThreadRequest, {}),
        (UpdateAnnotationThreadRequest, {"color": "yellow", "status": "open"}),
        (UpdateAnnotationThreadInput, {"thread_id": uuid4()}),
        (
            UpdateAnnotationThreadInput,
            {"thread_id": uuid4(), "color": "yellow", "status": "open"},
        ),
    ],
)
def test_update_annotation_thread_runtime_matches_exactly_one_schema(
    model: type[BaseModel], values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="exactly one|provide exactly one"):
        model.model_validate(values)


def test_annotation_thread_mutation_receipt_bounds_large_stored_content() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    document_id = uuid4()
    thread_id = uuid4()
    large_text = "🧪" * 100_000
    hostile_identity = '\x00\\"🙂' * 100_000
    thread = ResearchItemResponse(
        id=thread_id,
        kind=ResearchItemKind.ANNOTATION_THREAD,
        audience=PersonalResearchAudience(),
        target_document_id=document_id,
        created_by=ResearchCreatorResponse(id=7, display_name=hostile_identity),
        created_at=now,
        updated_at=now,
        capabilities=ResearchItemCapabilities(edit=True, delete=True),
        annotation_thread=AnnotationThreadContent(
            quote_text=large_text,
            position=ParsedTextPosition(start_offset=0, end_offset=100_000),
            color=AnnotationColor.YELLOW,
            role="assistant",
            mode=AnnotationThreadMode.HIGHLIGHT,
            comment_count=1,
            last_activity_at=now,
            status=AnnotationThreadStatus.OPEN,
            resolved_by=ResearchCreatorResponse(
                id=8,
                display_name=hostile_identity,
            ),
            resolved_at=None,
            capabilities=AnnotationThreadCapabilities(
                reply=True,
                recolor=True,
                resolve=True,
                reopen=False,
                delete=True,
            ),
            comments=[],
        ),
    )
    capabilities = MagicMock()
    capabilities.research_items.update_annotation_thread_bounded.return_value = thread

    outcome = _handler().update_annotation_thread(
        capabilities,
        _context(),
        UpdateAnnotationThreadInput(
            thread_id=thread_id,
            color=AnnotationColor.YELLOW,
        ),
    )
    capabilities.research_items.update_annotation_thread.assert_not_called()
    capabilities.research_items.update_annotation_thread_bounded.assert_called_once()

    receipt = ThreadActionOutput.model_validate(outcome.payload)
    annotation = receipt.thread.annotation_thread
    assert annotation is not None
    assert receipt.content_truncated is True
    assert annotation.position is None
    assert annotation.comments == []
    assert len(annotation.quote_text.encode("utf-8")) <= 4_096
    assert receipt.thread.created_by.display_name is not None
    assert annotation.resolved_by is not None
    receipt_data = receipt.model_dump(mode="json")
    assert {
        "kind",
        "updated_at",
        "capabilities",
        "annotation_thread",
        "citation",
        "audio_overview",
        "data_table",
    } <= receipt_data["thread"].keys()
    assert (
        len(
            json.dumps(
                receipt.thread.created_by.display_name,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ANNOTATION_MUTATION_IDENTITY_JSON_BYTES
    )
    assert (
        len(
            json.dumps(
                annotation.resolved_by.display_name,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ANNOTATION_MUTATION_IDENTITY_JSON_BYTES
    )
    assert thread.created_by.display_name == hostile_identity
    assert "thread" not in (outcome.action or {})
    assert (
        serialize_tool_success(outcome).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_annotation_comment_mutation_receipt_bounds_large_stored_content() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    hostile_identity = '\x00\\"🙂' * 100_000
    comment = AnnotationCommentResponse(
        id=uuid4(),
        thread_id=uuid4(),
        content="🧪" * 100_000,
        role="assistant",
        created_by=ResearchCreatorResponse(id=7, display_name=hostile_identity),
        created_at=now,
        updated_at=now,
        can_edit=True,
        can_delete=True,
    )
    capabilities = MagicMock()
    capabilities.research_items.update_comment.return_value = comment

    outcome = _handler().update_annotation_comment(
        capabilities,
        _context(),
        UpdateAnnotationCommentInput(
            comment_id=comment.id,
            content=comment.content,
        ),
    )

    receipt = CommentActionOutput.model_validate(outcome.payload)
    assert receipt.content_truncated is True
    assert len(receipt.comment.content.encode("utf-8")) <= 4_096
    assert receipt.comment.created_by.display_name is not None
    assert (
        len(
            json.dumps(
                receipt.comment.created_by.display_name,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ANNOTATION_MUTATION_IDENTITY_JSON_BYTES
    )
    assert comment.created_by.display_name == hostile_identity
    assert "comment" not in (outcome.action or {})
    assert (
        serialize_tool_success(outcome).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )
