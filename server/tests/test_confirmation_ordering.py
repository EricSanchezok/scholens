"""Regression tests for confirmation-flow business validation ordering.

Previously ``cancel_paper_ingestion`` and ``accept_project_invitation``
issued a confirmation preview before validating the job state or invitation
token, so invalid requests produced a useless preview instead of a structured
error. Business validation must run before the preview is issued.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
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
from app.shared.domain import AppError, FailureKind
from app.tooling.contracts import ToolExecutionContext
from app.tooling.workspace_contracts import (
    AcceptProjectInvitationInput,
    CancelPaperIngestionInput,
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
        invocation_id="confirmation-ordering-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="test-secret",
    )


def _completed_job() -> MagicMock:
    return MagicMock(status="completed")


@pytest.mark.asyncio
async def test_cancel_completed_ingestion_rejects_before_preview() -> None:
    handler = _handler()
    handler._executor.query.return_value = _completed_job()
    arguments = CancelPaperIngestionInput(job_id=uuid4())

    with pytest.raises(AppError) as excinfo:
        await handler.cancel_paper_ingestion(_context(), arguments, "test")

    assert excinfo.value.code == "paper_ingestion_cancel_not_allowed"
    assert excinfo.value.kind is FailureKind.CONFLICT
    handler._executor.command.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_active_ingestion_still_issues_preview() -> None:
    handler = _handler()
    handler._executor.query.return_value = MagicMock(status="running")
    handler._executor.command.side_effect = lambda fn: fn(MagicMock())
    arguments = CancelPaperIngestionInput(job_id=uuid4())

    outcome = await handler.cancel_paper_ingestion(_context(), arguments, "test")

    assert outcome is not None
    handler._executor.command.assert_called_once()


def test_accept_invitation_with_invalid_token_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    capabilities.projects.validate_invitation_token.side_effect = AppError(
        code="project_invitation_invalid",
        message="Invitation is invalid or expired",
        kind=FailureKind.NOT_FOUND,
    )
    arguments = AcceptProjectInvitationInput(token="garbage-token-value")

    with pytest.raises(AppError) as excinfo:
        handler.accept_project_invitation(capabilities, _context(), arguments)

    assert excinfo.value.code == "project_invitation_invalid"
    capabilities.action_confirmations.issue.assert_not_called()
