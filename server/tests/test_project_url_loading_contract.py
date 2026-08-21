from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.projects.application.contracts import ProjectPaperListResponse
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.tooling.contracts import ToolExecutionContext
from app.tooling.workspace_contracts import ListProjectPapersInput
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
        invocation_id="project-url-loading-contract",
        client_ip="test",
    )


def test_mcp_project_paper_listing_requests_neither_file_nor_preview_urls() -> None:
    handler = WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="project-url-loading-test-secret",
    )
    capabilities = MagicMock()
    capabilities.projects.documents.return_value = ProjectPaperListResponse(items=[])
    project_id = uuid4()
    context = _context()
    arguments = ListProjectPapersInput(project_id=project_id)

    handler.list_project_papers(
        capabilities,
        context,
        arguments,
    )

    capabilities.projects.documents.assert_called_once_with(
        actor=context.actor,
        project_id=project_id,
        load_urls=False,
        load_preview_urls=False,
        query=None,
        sort=arguments.sort,
        cursor=None,
        limit=20,
    )
