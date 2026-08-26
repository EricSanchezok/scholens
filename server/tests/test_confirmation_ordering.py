"""Regression tests for confirmation-flow business validation ordering.

Every confirmation-enabled tool must validate its complete non-mutating
business preconditions before issuing a preview. Invalid or already-satisfied
requests return a structured error or idempotent receipt without minting a
useless confirmation token.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.modules.action_confirmations.contracts import ConfirmationChallenge
from app.modules.jobs.application.contracts import JobResponse
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    DocumentResponse,
    LibraryPaperResponse,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
)
from app.modules.papers.application.ingestion import (
    IngestionCancellationPlan,
    IngestionCancellationState,
)
from app.modules.papers.application.library import (
    LibraryPaperConfirmationPlan,
    LibraryPaperConfirmationState,
)
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectCollaboratorResponse,
    ProjectInvitationDeliveryStatus,
    ProjectInvitationResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPermissionSet,
    ProjectResponse,
)
from app.modules.projects.application.lifecycle import (
    ProjectDeletionPlan,
    ProjectDeletionState,
    ProjectInvitationCreationPlan,
    ProjectInvitationCreationState,
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
from app.shared.domain import (
    WORKSPACE_PERMISSION_ORDER,
    AppError,
    FailureKind,
)
from app.shared.domain.enums import DocumentProcessingStatus, JobOperation, PaperStatus
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolDispatcher,
    ToolProfile,
)
from app.tooling.contracts import ToolExecutionContext, ToolOutcome
from app.tooling.invocations import tool_arguments_hash
from app.tooling.results import persisted_tool_outcome
from app.tooling.workspace import (
    CONVERSATION_TOOL_PROFILE,
    build_workspace_tool_catalog,
)
from app.tooling.workspace_contracts import (
    AcceptProjectInvitationInput,
    CancelPaperIngestionInput,
    CreateProjectInvitationInput,
    DeleteAnnotationCommentInput,
    DeleteAnnotationThreadInput,
    DeleteLibraryTagInput,
    DeleteProjectInput,
    InvitationInput,
    LeaveProjectInput,
    ProjectPaperInput,
    RemoveLibraryPapersInput,
    RemoveProjectMemberInput,
    SharedPaperInput,
    TransferProjectOwnershipInput,
    UpdateProjectMemberInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers

NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


class _ImpossibleOutcome(BaseModel):
    required_value: Literal["never"]


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


def _finalize_outcome(outcome: ToolOutcome) -> ToolOutcome:
    return outcome


def _atomic_dispatcher(
    *,
    capabilities: object,
    tool_name: str,
    output_model: type[BaseModel] | None = None,
    max_output_bytes: int | None = None,
    ingestion: MagicMock | None = None,
) -> tuple[ToolDispatcher, ToolAccess, MagicMock, list[str], MagicMock]:
    executor = MagicMock()
    committed_commands: list[str] = []
    executor.query.side_effect = lambda operation: operation(capabilities)

    def command(operation):
        result = operation(capabilities)
        committed_commands.append(tool_name)
        return result

    executor.command.side_effect = command
    ingestion = ingestion or MagicMock()
    source_catalog = build_workspace_tool_catalog(
        executor=executor,
        ingestion=ingestion,
        citations=MagicMock(),
    )
    source_access = ToolAccess(
        profile_name=CONVERSATION_TOOL_PROFILE,
        permissions=frozenset(WORKSPACE_PERMISSION_ORDER),
    )
    definition = source_catalog.definition_for(source_access, tool_name)
    replacements: dict[str, object] = {}
    if output_model is not None:
        replacements["output_model"] = output_model
    if max_output_bytes is not None:
        replacements["max_output_bytes"] = max_output_bytes
    definition = replace(definition, **replacements)
    profile_name = "atomic-receipt-test"
    catalog = ToolCatalog(
        [definition],
        [ToolProfile(name=profile_name, tool_names=frozenset({tool_name}))],
    )
    access = ToolAccess(
        profile_name=profile_name,
        permissions=frozenset({definition.required_permission}),
    )
    return (
        ToolDispatcher(catalog=catalog, executor=executor),
        access,
        executor,
        committed_commands,
        ingestion,
    )


def _permissions(
    *,
    edit_project: bool = False,
    manage_papers: bool = False,
    manage_collaborators: bool = False,
) -> ProjectPermissionSet:
    return ProjectPermissionSet(
        edit_project=edit_project,
        manage_papers=manage_papers,
        manage_collaborators=manage_collaborators,
    )


def _project(
    *,
    project_id: UUID | None = None,
    owner_id: int = 7,
    membership: ProjectPermissionSet | None = None,
) -> ProjectResponse:
    project_id = project_id or uuid4()
    permissions = membership or _permissions()
    return ProjectResponse(
        id=project_id,
        title="Evidence review",
        description=None,
        owner=ProjectOwnerResponse(
            id=owner_id,
            display_name="Owner",
            email=f"owner-{owner_id}@example.com",
        ),
        membership=ProjectMembershipResponse(
            kind="owner" if owner_id == _actor().id else "collaborator",
            permissions=permissions,
        ),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=owner_id == _actor().id or permissions.edit_project,
            manage_papers=owner_id == _actor().id or permissions.manage_papers,
            manage_collaborators=(
                owner_id == _actor().id or permissions.manage_collaborators
            ),
            transfer=owner_id == _actor().id,
            delete=owner_id == _actor().id,
            leave=owner_id != _actor().id,
        ),
        activity_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _collaborator(
    user_id: int,
    *,
    permissions: ProjectPermissionSet | None = None,
    is_owner: bool = False,
    email: str | None = None,
) -> ProjectCollaboratorResponse:
    return ProjectCollaboratorResponse(
        user_id=user_id,
        display_name=f"User {user_id}",
        email=email or f"user-{user_id}@example.com",
        is_owner=is_owner,
        permissions=permissions or _permissions(),
        joined_at=NOW,
    )


def _invitation(
    *,
    project_id,
    status: ProjectInvitationDeliveryStatus = ProjectInvitationDeliveryStatus.SENT,
) -> ProjectInvitationResponse:
    return ProjectInvitationResponse(
        id=uuid4(),
        project_id=project_id,
        project_name="Evidence review",
        email="invitee@example.com",
        invited_by="Owner",
        permissions=_permissions(),
        expires_at=NOW,
        created_at=NOW,
        delivery_status=status,
        delivered_at=NOW if status is ProjectInvitationDeliveryStatus.SENT else None,
    )


def _library_paper(*, is_public: bool) -> LibraryPaperResponse:
    document_id = uuid4()
    return LibraryPaperResponse(
        library_entry_id=uuid4(),
        user_id=_actor().id,
        status=PaperStatus.todo,
        last_accessed_at=NOW,
        metadata_overrides=DocumentMetadataOverrides(),
        is_public=is_public,
        preview_url=None,
        tags=[],
        document=DocumentResponse(
            document_id=document_id,
            original_filename="paper.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            title="Paper",
            authors=None,
            abstract=None,
            institutions=None,
            keywords=None,
            doi=None,
            journal=None,
            publisher=None,
            publish_date=None,
            summary=None,
            summary_citations=None,
            starter_questions=None,
            processing_status=DocumentProcessingStatus.COMPLETED,
            parser_quality="full",
            parser_warning_code=None,
            created_at=NOW,
            updated_at=NOW,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _job(status: str) -> JobResponse:
    return JobResponse(
        id=uuid4(),
        operation=JobOperation.PDF_PROCESS.value,
        document_id=uuid4(),
        project_id=None,
        status=status,
        progress_code=None,
        error_code=None,
        result={"internal": "must-not-bind-confirmation"},
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        started_at=None,
        completed_at=None,
    )


def _cancel_plan(
    *,
    job_id: UUID,
    status: Literal["pending", "running", "failed", "cancelled"],
    dismissed_at: datetime | None = None,
    project_id: UUID | None = None,
    library_membership_id: UUID | None = None,
    project_membership_id: UUID | None = None,
    document_gc_will_be_evaluated: bool = False,
) -> IngestionCancellationPlan:
    return IngestionCancellationPlan(
        state=IngestionCancellationState(
            job_id=job_id,
            status=status,
            job_updated_at=NOW,
            reservation_id=uuid4() if status != "cancelled" else None,
            reservation_updated_at=NOW if status != "cancelled" else None,
            dismissed_at=dismissed_at,
            document_id=uuid4(),
            project_id=project_id,
            library_reference_created=library_membership_id is not None,
            project_reference_created=project_membership_id is not None,
            library_membership_id=library_membership_id,
            project_membership_id=project_membership_id,
            document_gc_will_be_evaluated=document_gc_will_be_evaluated,
        )
    )


def _library_confirmation_plan(
    paper: LibraryPaperResponse,
    *,
    share_token_hash: str | None = None,
) -> LibraryPaperConfirmationPlan:
    return LibraryPaperConfirmationPlan(
        state=LibraryPaperConfirmationState(
            library_entry_id=paper.library_entry_id,
            document_id=paper.document.document_id,
            document_sha256="a" * 64,
            display_title=paper.document.title or paper.document.original_filename,
            is_public=paper.is_public,
            share_token_hash=share_token_hash,
        )
    )


def _confirmation_challenge() -> ConfirmationChallenge:
    return ConfirmationChallenge(
        confirmation_token="x" * 32,
        expires_at=NOW,
        impact={
            "title": "Confirm",
            "summary": "Confirm action",
            "consequences": [],
            "affected_resources": [],
        },
    )


def _invitation_creation_plan(
    *, project: ProjectResponse, arguments: CreateProjectInvitationInput
) -> ProjectInvitationCreationPlan:
    return ProjectInvitationCreationPlan(
        state=ProjectInvitationCreationState(
            project_id=project.id,
            project_updated_at=project.updated_at,
            normalized_email=str(arguments.email).lower(),
            requested_permissions=ProjectPermissionSet(
                edit_project=arguments.edit_project,
                manage_papers=arguments.manage_papers,
                manage_collaborators=arguments.manage_collaborators,
            ),
            replaced_invitation=None,
        ),
        project_title=project.title,
        replaced_invitation_id=None,
    )


def _project_deletion_plan(*, project_id: UUID, title: str) -> ProjectDeletionPlan:
    return ProjectDeletionPlan(
        state=ProjectDeletionState(
            project_id=project_id,
            owner_id=_actor().id,
            project_updated_at=NOW,
            paper_association_count=0,
            research_output_count=0,
            annotation_thread_count=0,
            annotation_comment_count=0,
            annotation_revision_digest="0" * 64,
            collaborator_count=0,
            invitation_count=0,
            conversation_count=0,
            storage_object_count=0,
            active_job_count=0,
            affected_resource_digest="a" * 64,
        ),
        project_title=title,
    )


@pytest.mark.asyncio
async def test_cancel_completed_ingestion_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    capabilities.paper_ingestion.plan_cancel.side_effect = AppError(
        code="paper_ingestion_cancel_not_allowed",
        message="Only pending or running paper ingestions can be cancelled",
        kind=FailureKind.CONFLICT,
    )
    handler._executor.command.side_effect = lambda fn: fn(capabilities)
    arguments = CancelPaperIngestionInput(job_id=uuid4())

    with pytest.raises(AppError) as excinfo:
        await handler.cancel_paper_ingestion(
            _context(), arguments, "test", _finalize_outcome
        )

    assert excinfo.value.code == "paper_ingestion_cancel_not_allowed"
    assert excinfo.value.kind is FailureKind.CONFLICT
    capabilities.action_confirmations.issue.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_active_ingestion_still_issues_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    arguments = CancelPaperIngestionInput(job_id=uuid4())
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="running",
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    outcome = await handler.cancel_paper_ingestion(
        _context(), arguments, "test", _finalize_outcome
    )

    assert outcome is not None
    handler._executor.command.assert_called_once()
    capabilities.tool_invocations.replay.assert_not_called()
    capabilities.tool_invocations.complete.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_preview_discloses_membership_removal_and_document_gc() -> None:
    handler = _handler()
    capabilities = MagicMock()
    arguments = CancelPaperIngestionInput(job_id=uuid4())
    project_id = uuid4()
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="running",
        project_id=project_id,
        library_membership_id=uuid4(),
        project_membership_id=uuid4(),
        document_gc_will_be_evaluated=True,
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    await handler.cancel_paper_ingestion(
        _context(), arguments, "cancel-preview", _finalize_outcome
    )

    impact = capabilities.action_confirmations.issue.call_args.kwargs["impact"]
    assert any("Library membership" in item for item in impact.consequences)
    assert any("Project paper association" in item for item in impact.consequences)
    assert any("orphan cleanup" in item for item in impact.consequences)
    assert f"project:{project_id}" in impact.affected_resources


@pytest.mark.asyncio
async def test_remove_failed_ingestion_discloses_retry_and_audit_consequences() -> None:
    handler = _handler()
    capabilities = MagicMock()
    arguments = CancelPaperIngestionInput(job_id=uuid4())
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="failed",
        document_gc_will_be_evaluated=True,
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    await handler.cancel_paper_ingestion(
        _context(), arguments, "remove-failed-preview", _finalize_outcome
    )

    impact = capabilities.action_confirmations.issue.call_args.kwargs["impact"]
    assert impact.title == "Remove failed paper ingestion"
    assert any("prevent another retry" in item for item in impact.consequences)
    assert any("immutable audit history" in item for item in impact.consequences)
    assert any("orphan cleanup" in item for item in impact.consequences)


@pytest.mark.asyncio
async def test_cancel_confirmed_mutation_replays_receipt_and_releases_again() -> None:
    handler = _handler()
    handler._ingestion.release_cancelled = AsyncMock()
    capabilities = MagicMock()
    context = _context()
    arguments = CancelPaperIngestionInput(
        job_id=uuid4(),
        confirmation_token="c" * 32,
        idempotency_key="cancel-receipt",
    )
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="running",
    )
    capabilities.paper_ingestion.cancel.return_value = True
    capabilities.tool_invocations.replay.return_value = None
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    first = await handler.cancel_paper_ingestion(
        context,
        arguments,
        "cancel-invocation",
        _finalize_outcome,
    )

    receipt_call = capabilities.tool_invocations.complete.call_args
    assert receipt_call.kwargs["arguments_hash"] == tool_arguments_hash(arguments)
    assert receipt_call.kwargs["result"] == persisted_tool_outcome(first)
    capabilities.action_confirmations.consume.assert_called_once()
    capabilities.paper_ingestion.cancel.assert_called_once()
    handler._ingestion.release_cancelled.assert_awaited_once_with(
        actor=context.actor,
        job_id=arguments.job_id,
    )

    capabilities.paper_ingestion.plan_cancel.reset_mock()
    capabilities.paper_ingestion.cancel.reset_mock()
    capabilities.action_confirmations.consume.reset_mock()
    capabilities.tool_invocations.complete.reset_mock()
    capabilities.tool_invocations.replay.return_value = receipt_call.kwargs["result"]
    handler._ingestion.release_cancelled.reset_mock()

    replayed = await handler.cancel_paper_ingestion(
        context,
        arguments,
        "cancel-invocation",
        _finalize_outcome,
    )

    assert replayed == first
    capabilities.paper_ingestion.plan_cancel.assert_not_called()
    capabilities.paper_ingestion.cancel.assert_not_called()
    capabilities.action_confirmations.consume.assert_not_called()
    capabilities.tool_invocations.complete.assert_not_called()
    handler._ingestion.release_cancelled.assert_awaited_once_with(
        actor=context.actor,
        job_id=arguments.job_id,
    )


@pytest.mark.asyncio
async def test_cancel_cancelled_ingestion_is_idempotent_without_preview() -> None:
    handler = _handler()
    arguments = CancelPaperIngestionInput(job_id=uuid4())
    capabilities = MagicMock()
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="cancelled",
    )
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    outcome = await handler.cancel_paper_ingestion(
        _context(), arguments, "test", _finalize_outcome
    )

    assert outcome.action is not None
    assert outcome.action["action"] == "paper_ingestion_cancelled"
    assert outcome.action["changed"] is False
    assert outcome.action["affected_resources"] == [f"job:{arguments.job_id}"]
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.paper_ingestion.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_remove_dismissed_failed_ingestion_is_idempotent_without_preview() -> (
    None
):
    handler = _handler()
    arguments = CancelPaperIngestionInput(job_id=uuid4())
    capabilities = MagicMock()
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="failed",
        dismissed_at=NOW,
    )
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    outcome = await handler.cancel_paper_ingestion(
        _context(), arguments, "test", _finalize_outcome
    )

    assert outcome.action is not None
    assert outcome.action["action"] == "paper_ingestion_removed"
    assert outcome.action["changed"] is False
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.paper_ingestion.cancel.assert_not_called()


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
    capabilities.projects.validate_invitation_token.assert_called_once_with(
        actor=_context().actor,
        raw_token="garbage-token-value",
    )


def test_delete_project_requires_owner_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project(
        owner_id=99,
        membership=_permissions(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=True,
        ),
    )
    capabilities.projects.plan_delete.side_effect = AppError(
        code="project_permission_denied",
        message="Project permission denied",
        kind=FailureKind.PERMISSION_DENIED,
    )

    with pytest.raises(AppError) as excinfo:
        handler.delete_project(
            capabilities,
            _context(),
            DeleteProjectInput(project_id=project.id),
        )

    assert excinfo.value.code == "project_permission_denied"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.delete.assert_not_called()


def test_delete_project_impact_is_bounded_for_maximum_project_title() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project_id = uuid4()
    capabilities.projects.plan_delete.return_value = _project_deletion_plan(
        project_id=project_id,
        title="P" * 240,
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()

    handler.delete_project(
        capabilities,
        _context(),
        DeleteProjectInput(project_id=project_id),
    )

    impact = capabilities.action_confirmations.issue.call_args.kwargs["impact"]
    assert len(impact.title) <= 160
    assert len(impact.summary) <= 1_000


def test_remove_project_paper_requires_manage_permission_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project_id = uuid4()
    document_id = uuid4()
    capabilities.projects.plan_remove_document.side_effect = AppError(
        code="project_permission_denied",
        message="Project permission denied",
        kind=FailureKind.PERMISSION_DENIED,
    )

    with pytest.raises(AppError) as excinfo:
        handler.remove_paper_from_project(
            capabilities,
            _context(),
            ProjectPaperInput(project_id=project_id, document_id=document_id),
        )

    assert excinfo.value.code == "project_permission_denied"
    capabilities.projects.plan_remove_document.assert_called_once_with(
        actor=_context().actor,
        project_id=project_id,
        document_id=document_id,
    )
    capabilities.action_confirmations.issue.assert_not_called()


def test_remove_project_paper_requires_existing_association_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project_id = uuid4()
    document_id = uuid4()
    capabilities.projects.plan_remove_document.side_effect = AppError(
        code="project_document_not_found",
        message="Document not found in this Project",
        kind=FailureKind.NOT_FOUND,
    )

    with pytest.raises(AppError) as excinfo:
        handler.remove_paper_from_project(
            capabilities,
            _context(),
            ProjectPaperInput(project_id=project_id, document_id=document_id),
        )

    assert excinfo.value.code == "project_document_not_found"
    capabilities.projects.plan_remove_document.assert_called_once_with(
        actor=_context().actor,
        project_id=project_id,
        document_id=document_id,
    )
    capabilities.action_confirmations.issue.assert_not_called()


@pytest.mark.asyncio
async def test_create_invitation_rejects_existing_member_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    capabilities.projects.plan_invitation_creation.side_effect = AppError(
        code="project_collaborator_exists",
        message="This user already belongs to the Project",
        kind=FailureKind.CONFLICT,
    )

    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    with pytest.raises(AppError) as excinfo:
        await handler.create_project_invitation(
            _context(),
            CreateProjectInvitationInput(
                project_id=project.id,
                email="Invitee@Example.com",
                edit_project=False,
                manage_papers=False,
                manage_collaborators=False,
            ),
            "create-invitation-test",
            _finalize_outcome,
        )

    assert excinfo.value.code == "project_collaborator_exists"
    capabilities.action_confirmations.issue.assert_not_called()


@pytest.mark.asyncio
async def test_create_invitation_preview_does_not_persist_receipt() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    arguments = CreateProjectInvitationInput(
        project_id=project.id,
        email="Invitee@Example.com",
        edit_project=False,
        manage_papers=True,
        manage_collaborators=False,
    )
    capabilities.projects.plan_invitation_creation.return_value = (
        _invitation_creation_plan(project=project, arguments=arguments)
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    outcome = await handler.create_project_invitation(
        _context(),
        arguments,
        "create-preview",
        _finalize_outcome,
    )

    assert outcome.payload["status"] == "confirmation_required"
    capabilities.tool_invocations.replay.assert_not_called()
    capabilities.tool_invocations.complete.assert_not_called()
    capabilities.projects.create_invitation.assert_not_called()


@pytest.mark.asyncio
async def test_create_invitation_confirmed_mutation_replays_atomic_receipt() -> None:
    handler = _handler()
    capabilities = MagicMock()
    context = _context()
    project = _project()
    arguments = CreateProjectInvitationInput(
        project_id=project.id,
        email="Invitee@Example.com",
        edit_project=False,
        manage_papers=True,
        manage_collaborators=False,
        confirmation_token="c" * 32,
        idempotency_key="create-invitation-receipt",
    )
    invitation = _invitation(project_id=project.id)
    capabilities.projects.plan_invitation_creation.return_value = (
        _invitation_creation_plan(project=project, arguments=arguments)
    )
    capabilities.projects.create_invitation.return_value = invitation
    capabilities.tool_invocations.replay.return_value = None
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    first = await handler.create_project_invitation(
        context,
        arguments,
        "create-invitation",
        _finalize_outcome,
    )

    receipt_call = capabilities.tool_invocations.complete.call_args
    assert receipt_call.kwargs["tool_name"] == "create_project_invitation"
    assert receipt_call.kwargs["arguments_hash"] == tool_arguments_hash(arguments)
    assert receipt_call.kwargs["result"] == persisted_tool_outcome(first)
    capabilities.action_confirmations.consume.assert_called_once()
    capabilities.projects.create_invitation.assert_called_once()

    capabilities.projects.plan_invitation_creation.reset_mock()
    capabilities.projects.create_invitation.reset_mock()
    capabilities.action_confirmations.consume.reset_mock()
    capabilities.tool_invocations.complete.reset_mock()
    capabilities.tool_invocations.replay.return_value = receipt_call.kwargs["result"]

    replayed = await handler.create_project_invitation(
        context,
        arguments,
        "create-invitation",
        _finalize_outcome,
    )

    assert replayed == first
    capabilities.projects.plan_invitation_creation.assert_not_called()
    capabilities.projects.create_invitation.assert_not_called()
    capabilities.action_confirmations.consume.assert_not_called()
    capabilities.tool_invocations.complete.assert_not_called()


@pytest.mark.asyncio
async def test_invitation_schema_failure_aborts_business_and_receipt_transaction() -> (
    None
):
    capabilities = MagicMock()
    context = _context()
    project = _project()
    arguments = CreateProjectInvitationInput(
        project_id=project.id,
        email="invitee@example.com",
        edit_project=False,
        manage_papers=False,
        manage_collaborators=False,
        confirmation_token="c" * 32,
        idempotency_key="schema-failure",
    )
    capabilities.projects.plan_invitation_creation.return_value = (
        _invitation_creation_plan(project=project, arguments=arguments)
    )
    capabilities.projects.create_invitation.return_value = _invitation(
        project_id=project.id
    )
    capabilities.tool_invocations.replay.return_value = None
    dispatcher, access, executor, committed, _ingestion = _atomic_dispatcher(
        capabilities=capabilities,
        tool_name="create_project_invitation",
        output_model=_ImpossibleOutcome,
    )

    with pytest.raises(AppError) as error:
        await dispatcher.dispatch(
            name="create_project_invitation",
            raw_arguments=arguments.model_dump(mode="json"),
            context=context,
            access=access,
        )

    assert error.value.code == "tool_result_invalid"
    assert committed == []
    assert executor.command.call_count == 1
    capabilities.projects.create_invitation.assert_called_once()
    capabilities.tool_invocations.complete.assert_not_called()


@pytest.mark.asyncio
async def test_resend_pending_invitation_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    invitation = _invitation(
        project_id=project.id,
        status=ProjectInvitationDeliveryStatus.PENDING,
    )
    capabilities.projects.get.return_value = project
    capabilities.projects.invitation.return_value = invitation
    handler._executor.command.side_effect = lambda fn: fn(capabilities)
    with pytest.raises(AppError) as excinfo:
        await handler.resend_project_invitation(
            _context(),
            InvitationInput(
                project_id=project.id,
                invitation_id=invitation.id,
            ),
            "resend-invitation-test",
            _finalize_outcome,
        )

    assert excinfo.value.code == "project_invitation_delivery_pending"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.resend_invitation.assert_not_called()


@pytest.mark.asyncio
async def test_resend_invitation_confirmed_mutation_replays_atomic_receipt() -> None:
    handler = _handler()
    capabilities = MagicMock()
    context = _context()
    project = _project()
    invitation = _invitation(project_id=project.id)
    resent = _invitation(
        project_id=project.id,
        status=ProjectInvitationDeliveryStatus.PENDING,
    )
    arguments = InvitationInput(
        project_id=project.id,
        invitation_id=invitation.id,
        confirmation_token="c" * 32,
        idempotency_key="resend-invitation-receipt",
    )
    capabilities.projects.get.return_value = project
    capabilities.projects.invitation.return_value = invitation
    capabilities.projects.resend_invitation.return_value = resent
    capabilities.tool_invocations.replay.return_value = None
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    first = await handler.resend_project_invitation(
        context,
        arguments,
        "resend-invitation",
        _finalize_outcome,
    )

    receipt_call = capabilities.tool_invocations.complete.call_args
    assert receipt_call.kwargs["tool_name"] == "resend_project_invitation"
    assert receipt_call.kwargs["arguments_hash"] == tool_arguments_hash(arguments)
    assert receipt_call.kwargs["result"] == persisted_tool_outcome(first)
    capabilities.action_confirmations.consume.assert_called_once()
    capabilities.projects.resend_invitation.assert_called_once()

    capabilities.projects.get.reset_mock()
    capabilities.projects.invitations.reset_mock()
    capabilities.projects.resend_invitation.reset_mock()
    capabilities.action_confirmations.consume.reset_mock()
    capabilities.tool_invocations.complete.reset_mock()
    capabilities.tool_invocations.replay.return_value = receipt_call.kwargs["result"]

    replayed = await handler.resend_project_invitation(
        context,
        arguments,
        "resend-invitation",
        _finalize_outcome,
    )

    assert replayed == first
    capabilities.projects.get.assert_not_called()
    capabilities.projects.invitations.assert_not_called()
    capabilities.projects.resend_invitation.assert_not_called()
    capabilities.action_confirmations.consume.assert_not_called()
    capabilities.tool_invocations.complete.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_budget_failure_aborts_business_and_receipt_transaction() -> None:
    capabilities = MagicMock()
    context = _context()
    arguments = CancelPaperIngestionInput(
        job_id=uuid4(),
        confirmation_token="c" * 32,
        idempotency_key="budget-failure",
    )
    capabilities.paper_ingestion.plan_cancel.return_value = _cancel_plan(
        job_id=arguments.job_id,
        status="running",
    )
    capabilities.paper_ingestion.cancel.return_value = True
    capabilities.tool_invocations.replay.return_value = None
    ingestion = MagicMock()
    ingestion.release_cancelled = AsyncMock()
    dispatcher, access, executor, committed, ingestion = _atomic_dispatcher(
        capabilities=capabilities,
        tool_name="cancel_paper_ingestion",
        max_output_bytes=1,
        ingestion=ingestion,
    )

    with pytest.raises(AppError) as error:
        await dispatcher.dispatch(
            name="cancel_paper_ingestion",
            raw_arguments=arguments.model_dump(mode="json"),
            context=context,
            access=access,
        )

    assert error.value.code == "tool_result_budget_exceeded"
    assert committed == []
    assert executor.command.call_count == 1
    capabilities.paper_ingestion.cancel.assert_called_once()
    capabilities.tool_invocations.complete.assert_not_called()
    ingestion.release_cancelled.assert_not_awaited()


def test_revoke_missing_invitation_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    capabilities.projects.get.return_value = project
    capabilities.projects.invitation.return_value = None

    with pytest.raises(AppError) as excinfo:
        handler.revoke_project_invitation(
            capabilities,
            _context(),
            InvitationInput(project_id=project.id, invitation_id=uuid4()),
        )

    assert excinfo.value.code == "project_invitation_not_found"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.revoke_invitation.assert_not_called()


def test_update_member_rejects_unmanageable_target_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    owner = _collaborator(_actor().id, is_owner=True)
    capabilities.projects.get.return_value = project
    capabilities.projects.member.return_value = owner

    with pytest.raises(AppError) as excinfo:
        handler.update_project_member(
            capabilities,
            _context(),
            UpdateProjectMemberInput(
                project_id=project.id,
                user_id=owner.user_id,
                edit_project=False,
                manage_papers=False,
                manage_collaborators=False,
            ),
        )

    assert excinfo.value.code == "project_collaborator_not_manageable"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.update_member.assert_not_called()


def test_unchanged_member_permissions_are_idempotent_without_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    target = _collaborator(12, permissions=_permissions(manage_papers=True))
    capabilities.projects.get.return_value = project
    capabilities.projects.member.return_value = target

    outcome = handler.update_project_member(
        capabilities,
        _context(),
        UpdateProjectMemberInput(
            project_id=project.id,
            user_id=target.user_id,
            edit_project=False,
            manage_papers=True,
            manage_collaborators=False,
        ),
    )

    assert outcome.action is not None
    assert outcome.action["changed"] is False
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.update_member.assert_not_called()


def test_remove_member_rejects_actor_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    actor_member = _collaborator(_actor().id, is_owner=True)
    capabilities.projects.get.return_value = project
    capabilities.projects.member.return_value = actor_member

    with pytest.raises(AppError) as excinfo:
        handler.remove_project_member(
            capabilities,
            _context(),
            RemoveProjectMemberInput(
                project_id=project.id,
                user_id=actor_member.user_id,
            ),
        )

    assert excinfo.value.code == "project_collaborator_not_manageable"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.remove_member.assert_not_called()


def test_owner_cannot_leave_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    capabilities.projects.get.return_value = project

    with pytest.raises(AppError) as excinfo:
        handler.leave_project(
            capabilities,
            _context(),
            LeaveProjectInput(project_id=project.id),
        )

    assert excinfo.value.code == "project_owner_must_transfer"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.leave.assert_not_called()


def test_transfer_requires_existing_non_owner_member_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    project = _project()
    capabilities.projects.plan_transfer.side_effect = AppError(
        code="project_new_owner_not_collaborator",
        message="The new owner must already be a collaborator",
        kind=FailureKind.CONFLICT,
    )

    with pytest.raises(AppError) as excinfo:
        handler.transfer_project_ownership(
            capabilities,
            _context(),
            TransferProjectOwnershipInput(
                project_id=project.id,
                new_owner_id=12,
            ),
        )

    assert excinfo.value.code == "project_new_owner_not_collaborator"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.projects.transfer.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("remove_library_papers", RemoveLibraryPapersInput(document_ids=[uuid4()])),
        ("share_library_paper", SharedPaperInput(document_id=uuid4())),
        ("unshare_library_paper", SharedPaperInput(document_id=uuid4())),
    ],
)
def test_library_paper_must_exist_before_preview(
    method_name: str,
    arguments: BaseModel,
) -> None:
    handler = _handler()
    capabilities = MagicMock()
    plan_method = (
        capabilities.paper_library.removal_plan
        if method_name == "remove_library_papers"
        else capabilities.paper_library.confirmation_plan
    )
    plan_method.side_effect = AppError(
        code="library_paper_not_found",
        message="Library paper not found",
        kind=FailureKind.NOT_FOUND,
    )

    with pytest.raises(AppError) as excinfo:
        getattr(handler, method_name)(capabilities, _context(), arguments)

    assert excinfo.value.code == "library_paper_not_found"
    capabilities.action_confirmations.issue.assert_not_called()


def test_remove_library_papers_keeps_legacy_duplicate_ids_valid() -> None:
    document_id = uuid4()
    parsed = RemoveLibraryPapersInput(document_ids=[document_id, document_id])
    handler = _handler()
    capabilities = MagicMock()
    capabilities.paper_library.removal_plan.side_effect = AppError(
        code="library_paper_not_found",
        message="Library paper not found",
        kind=FailureKind.NOT_FOUND,
    )

    with pytest.raises(AppError, match="library_paper_not_found"):
        handler.remove_library_papers(capabilities, _context(), parsed)

    assert parsed.document_ids == [document_id, document_id]
    assert (
        parsed.model_json_schema()["properties"]["document_ids"].get("uniqueItems")
        is None
    )
    assert capabilities.paper_library.removal_plan.call_args.kwargs["document_ids"] == (
        document_id,
    )


def test_private_paper_unshare_is_idempotent_without_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    paper = _library_paper(is_public=False)
    capabilities.paper_library.confirmation_plan.return_value = (
        _library_confirmation_plan(paper)
    )

    outcome = handler.unshare_library_paper(
        capabilities,
        _context(),
        SharedPaperInput(document_id=paper.document.document_id),
    )

    assert outcome.action is not None
    assert outcome.action["changed"] is False
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.paper_library.unshare.assert_not_called()


def test_share_paper_impact_bounds_untrusted_document_title() -> None:
    handler = _handler()
    capabilities = MagicMock()
    document_id = uuid4()
    capabilities.paper_library.confirmation_plan.return_value = (
        LibraryPaperConfirmationPlan(
            state=LibraryPaperConfirmationState(
                library_entry_id=uuid4(),
                document_id=document_id,
                document_sha256="a" * 64,
                display_title="T" * 10_000,
                is_public=False,
                share_token_hash=None,
            )
        )
    )
    capabilities.action_confirmations.issue.return_value = _confirmation_challenge()

    handler.share_library_paper(
        capabilities,
        _context(),
        SharedPaperInput(document_id=document_id),
    )

    impact = capabilities.action_confirmations.issue.call_args.kwargs["impact"]
    assert len(impact.title) <= 160
    assert len(impact.summary) <= 1_000


def test_delete_missing_library_tag_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    capabilities.library_tags.get.return_value = None

    with pytest.raises(AppError) as excinfo:
        handler.delete_library_tag(
            capabilities,
            _context(),
            DeleteLibraryTagInput(tag_id=uuid4()),
        )

    assert excinfo.value.code == "library_tag_not_found"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.library_tags.delete.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_non_ingestion_job_rejects_before_preview() -> None:
    handler = _handler()
    job = _job("running").model_copy(update={"operation": "data_table"})
    capabilities = MagicMock()
    capabilities.paper_ingestion.plan_cancel.side_effect = AppError(
        code="paper_ingestion_job_not_found",
        message="Paper ingestion job not found",
        kind=FailureKind.NOT_FOUND,
    )
    handler._executor.command.side_effect = lambda fn: fn(capabilities)

    with pytest.raises(AppError) as excinfo:
        await handler.cancel_paper_ingestion(
            _context(),
            CancelPaperIngestionInput(job_id=job.id),
            "test",
            _finalize_outcome,
        )

    assert excinfo.value.code == "paper_ingestion_job_not_found"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.paper_ingestion.cancel.assert_not_called()


def test_thread_with_other_contributor_replies_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    thread_id = uuid4()
    capabilities.research_items.plan_annotation_thread_delete.side_effect = AppError(
        code="annotation_thread_has_other_replies",
        message="Resolve this thread to preserve other contributors' replies",
        kind=FailureKind.CONFLICT,
        details={"affected_reply_count": 1},
    )

    with pytest.raises(AppError) as excinfo:
        handler.delete_annotation_thread(
            capabilities,
            _context(),
            DeleteAnnotationThreadInput(thread_id=thread_id),
        )

    assert excinfo.value.code == "annotation_thread_has_other_replies"
    capabilities.research_items.plan_annotation_thread_delete.assert_called_once_with(
        actor=_context().actor,
        thread_id=thread_id,
    )
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.research_items.delete_annotation_thread.assert_not_called()


def test_undeletable_comment_rejects_before_preview() -> None:
    handler = _handler()
    capabilities = MagicMock()
    comment = MagicMock(can_delete=False)
    capabilities.research_items.get_comment.return_value = comment

    with pytest.raises(AppError) as excinfo:
        handler.delete_annotation_comment(
            capabilities,
            _context(),
            DeleteAnnotationCommentInput(comment_id=uuid4()),
        )

    assert excinfo.value.code == "annotation_comment_not_found"
    capabilities.action_confirmations.issue.assert_not_called()
    capabilities.research_items.delete_comment.assert_not_called()
