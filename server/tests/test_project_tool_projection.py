from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.papers.application.contracts.documents import LibraryPaperTagResponse
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectListResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPaperListResponse,
    ProjectPaperSummaryResponse,
    ProjectPermissionSet,
    ProjectResponse,
)
from app.modules.projects.application.projects import (
    ProjectPaperSummaryList,
    ProjectSummaryList,
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
from app.shared.domain.enums import PaperStatus
from app.tooling import DEFAULT_TOOL_OUTPUT_BYTES, serialize_tool_success
from app.tooling.contracts import ToolExecutionContext
from app.tooling.project_summary_projection import (
    PROJECT_DETAIL_DESCRIPTION_JSON_BYTES,
    PROJECT_DESCRIPTION_JSON_BYTES,
    PROJECT_LIST_MAX_PAGE_ITEMS,
    PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
    project_project_list,
    project_project_paper_list,
)
from app.tooling.workspace_contracts import (
    ListPaperProjectsInput,
    ListProjectPapersInput,
    ListProjectsInput,
    ProjectInput,
    ProjectListToolOutput,
    ProjectPaperListToolOutput,
    UpdateProjectInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


def _context() -> ToolExecutionContext:
    actor = Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=actor,
        operation=operation,
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="project-tool-projection-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="project-tool-projection-secret",
    )


def _project(*, text: str) -> ProjectResponse:
    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    return ProjectResponse(
        id=uuid4(),
        title=text,
        description=text,
        owner=ProjectOwnerResponse(
            id=7,
            display_name=text,
            email="researcher@example.com",
        ),
        membership=ProjectMembershipResponse(
            kind="owner",
            permissions=ProjectPermissionSet(
                edit_project=True,
                manage_papers=True,
                manage_collaborators=True,
            ),
        ),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=True,
            transfer=True,
            delete=True,
            leave=False,
        ),
        num_papers=100,
        num_conversations=100,
        num_outputs=100,
        num_collaborators=100,
        activity_at=now,
        created_at=now,
        updated_at=now,
    )


def _paper(*, text: str) -> ProjectPaperSummaryResponse:
    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    return ProjectPaperSummaryResponse(
        document_id=uuid4(),
        title=text,
        added_at=now,
        abstract=text,
        authors=[text for _ in range(100)],
        institutions=[text for _ in range(100)],
        status="reading",
        journal=text,
        publisher=text,
        doi=text,
        publish_date=None,
        file_url="https://signed.example/private-paper",
        preview_url="https://signed.example/private-preview",
        summary=text,
        keywords=[text for _ in range(100)],
        in_library=True,
        personal_status=PaperStatus.reading,
        personal_tags=[
            LibraryPaperTagResponse(id=uuid4(), name=text, color=text)
            for _ in range(100)
        ],
        personal_last_accessed_at=now,
    )


def test_list_projects_max_input_returns_bounded_summaries_and_continuation() -> None:
    hostile = '\x00\\"中🙂' * 2_000
    original = [_project(text=hostile) for _ in range(PROJECT_LIST_MAX_PAGE_ITEMS)]
    projection = project_project_list(
        ProjectListResponse(
            items=original,
            next_cursor="signed-project-continuation",
            total_count=100,
        )
    )
    capabilities = MagicMock()
    capabilities.projects.summary_list.return_value = ProjectSummaryList(
        value=projection.value,
        content_truncated=projection.content_truncated,
    )
    capabilities.projects.list.side_effect = AssertionError("full path must not run")

    outcome = _handler().list_projects(
        capabilities,
        _context(),
        ListProjectsInput(limit=100),
    )
    page = ProjectListToolOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert capabilities.projects.summary_list.call_args.kwargs["limit"] == (
        PROJECT_LIST_MAX_PAGE_ITEMS
    )
    capabilities.projects.list.assert_not_called()
    assert page.next_cursor == "signed-project-continuation"
    assert page.content_truncated is True
    assert "get_project" in page.guidance
    assert all(
        len(json.dumps(item.description, ensure_ascii=False).encode("utf-8"))
        <= PROJECT_DESCRIPTION_JSON_BYTES
        for item in page.items
    )
    assert original[0].description == hostile
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES


def test_list_paper_projects_uses_same_bounded_project_projection() -> None:
    hostile = "🙂" * 10_000
    projects = [_project(text=hostile) for _ in range(PROJECT_LIST_MAX_PAGE_ITEMS)]
    projection = project_project_list(
        ProjectListResponse(
            items=projects,
            next_cursor="signed-paper-project-continuation",
            total_count=100,
        )
    )
    capabilities = MagicMock()
    capabilities.projects.project_summaries_for_document_page.return_value = (
        ProjectSummaryList(
            value=projection.value,
            content_truncated=projection.content_truncated,
        )
    )
    capabilities.projects.projects_for_document_page.side_effect = AssertionError(
        "full path must not run"
    )
    document_id = uuid4()

    outcome = _handler().list_paper_projects(
        capabilities,
        _context(),
        ListPaperProjectsInput(document_id=document_id, limit=25),
    )
    page = ProjectListToolOutput.model_validate(outcome.payload)

    assert page.next_cursor == "signed-paper-project-continuation"
    assert page.content_truncated is True
    assert len(page.items) == PROJECT_LIST_MAX_PAGE_ITEMS
    capabilities.projects.projects_for_document_page.assert_not_called()
    assert serialize_tool_success(outcome).call_tool_result_utf8_bytes < (
        DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_get_and_update_project_bound_escape_heavy_historical_values() -> None:
    hostile = "\\" * 100_000
    project = _project(text=hostile)
    capabilities = MagicMock()
    capabilities.projects.get.return_value = project
    capabilities.projects.update.return_value = project
    handler = _handler()
    context = _context()

    get_outcome = handler.get_project(
        capabilities,
        context,
        ProjectInput(project_id=project.id),
    )
    update_outcome = handler.update_project(
        capabilities,
        context,
        UpdateProjectInput(project_id=project.id, title="bounded update"),
    )

    for outcome in (get_outcome, update_outcome):
        payload = outcome.payload
        assert isinstance(payload, dict)
        assert payload["content_truncated"] is True
        description = payload["description"]
        assert isinstance(description, str)
        assert (
            len(json.dumps(description, ensure_ascii=False).encode("utf-8"))
            <= PROJECT_DETAIL_DESCRIPTION_JSON_BYTES
        )
        assert (
            serialize_tool_success(outcome).call_tool_result_utf8_bytes
            < DEFAULT_TOOL_OUTPUT_BYTES
        )


def test_list_project_papers_max_input_bounds_every_large_metadata_lane() -> None:
    hostile = '\x00\\"中🙂' * 20_000
    original = [_paper(text=hostile) for _ in range(PROJECT_PAPER_LIST_MAX_PAGE_ITEMS)]
    projection = project_project_paper_list(
        ProjectPaperListResponse(
            items=original,
            next_cursor="signed-project-paper-continuation",
            total_count=100,
        )
    )
    capabilities = MagicMock()
    capabilities.projects.document_summaries.return_value = ProjectPaperSummaryList(
        value=projection.value,
        content_truncated=projection.content_truncated,
    )
    capabilities.projects.documents.side_effect = AssertionError(
        "full path must not run"
    )
    project_id = uuid4()

    outcome = _handler().list_project_papers(
        capabilities,
        _context(),
        ListProjectPapersInput(project_id=project_id, limit=100),
    )
    page = ProjectPaperListToolOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert capabilities.projects.document_summaries.call_args.kwargs["limit"] == (
        PROJECT_PAPER_LIST_MAX_PAGE_ITEMS
    )
    capabilities.projects.documents.assert_not_called()
    assert page.next_cursor == "signed-project-paper-continuation"
    assert page.content_truncated is True
    assert "get_paper_page" in page.guidance
    assert all(
        item.file_url is None and item.preview_url is None for item in page.items
    )
    assert all(len(item.authors or []) <= 6 for item in page.items)
    assert all(len(item.institutions or []) <= 4 for item in page.items)
    assert all(len(item.keywords) <= 8 for item in page.items)
    assert all(len(item.personal_tags) <= 8 for item in page.items)
    assert original[0].abstract == hostile
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES
