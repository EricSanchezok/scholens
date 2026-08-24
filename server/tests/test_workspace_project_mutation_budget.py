from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPermissionSet,
    ProjectInvitationDeliveryStatus,
    ProjectInvitationResponse,
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectResponse,
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
from app.tooling import serialize_tool_success
from app.tooling.contracts import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    ToolExecutionContext,
    ToolOutcome,
)
from app.tooling.workspace_collection_projection import project_invitation_action
from app.tooling.workspace_contracts import (
    ConfirmationAwareAction,
    CompletedAction,
    CreateProjectInput,
    ListProjectMembersInput,
    ProjectInput,
    ProjectMemberListToolOutput,
    ProjectToolResponse,
    RemoveProjectMemberInput,
    UpdateProjectInput,
    UpdateProjectMemberInput,
    TransferProjectOwnershipInput,
    MemberInput,
    InvitationInput,
    LeaveProjectInput,
    ProjectPaperInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


def _context() -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation,
        paper_collection=MagicMock(),
        anchor_document_id=None,
        invocation_id="project-mutation-budget-test",
        client_ip="test",
    )


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (MemberInput, "user_id"),
        (UpdateProjectMemberInput, "user_id"),
        (RemoveProjectMemberInput, "user_id"),
        (TransferProjectOwnershipInput, "new_owner_id"),
    ],
)
def test_project_member_user_ids_match_the_persisted_bigint_range(
    model: type[MemberInput],
    field: str,
) -> None:
    project_id = uuid4()
    maximum = (1 << 63) - 1
    arguments: dict[str, object] = {"project_id": project_id, field: maximum}
    if model is UpdateProjectMemberInput:
        arguments.update(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=False,
        )

    assert getattr(model.model_validate(arguments), field) == maximum
    assert model.model_json_schema()["properties"][field]["maximum"] == maximum
    with pytest.raises(ValidationError):
        model.model_validate({**arguments, field: maximum + 1})


def _project(*, description: str) -> ProjectResponse:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    permissions = ProjectPermissionSet(
        edit_project=True,
        manage_papers=True,
        manage_collaborators=True,
    )
    return ProjectResponse(
        id=uuid4(),
        title="Research Project",
        description=description,
        owner=ProjectOwnerResponse(
            id=7,
            display_name="Researcher",
            email="reader@example.com",
        ),
        membership=ProjectMembershipResponse(kind="owner", permissions=permissions),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=True,
            transfer=True,
            delete=True,
            leave=False,
        ),
        activity_at=now,
        created_at=now,
        updated_at=now,
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="project-mutation-budget-secret",
    )


@pytest.mark.parametrize("operation", ["create", "update"])
def test_project_mutation_receipt_does_not_duplicate_large_description(
    operation: str,
) -> None:
    project = _project(description="\x01" * 10_000)
    capabilities = MagicMock()
    if operation == "create":
        capabilities.projects.create.return_value = project
        outcome = _handler().create_project(
            capabilities,
            _context(),
            CreateProjectInput(title=project.title, description=project.description),
        )
    else:
        capabilities.projects.update.return_value = project
        outcome = _handler().update_project(
            capabilities,
            _context(),
            UpdateProjectInput(
                project_id=project.id,
                description=project.description,
            ),
        )

    assert outcome.action is not None
    assert "project" not in outcome.action
    assert outcome.action["project_id"] == str(project.id)
    assert (
        serialize_tool_success(outcome).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_completed_action_keeps_large_result_only_in_payload() -> None:
    project = _project(description="\x01" * 10_000)

    outcome = _handler()._completed(
        action="project_ownership_transferred",
        affected_resources=[f"project:{project.id}"],
        result=project,
    )

    assert outcome.action is not None
    assert outcome.action["result"] is None
    assert (
        serialize_tool_success(outcome).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_get_project_bounds_unsupported_historical_owner_display_name() -> None:
    project = _project(description="supported")
    project.owner.display_name = "\x01🧪" * 100_000
    capabilities = MagicMock()
    capabilities.projects.get.return_value = project

    outcome = _handler().get_project(
        capabilities,
        _context(),
        ProjectInput(project_id=project.id),
    )

    response = ProjectToolResponse.model_validate(outcome.payload)
    assert response.content_truncated is True
    assert response.guidance is not None
    assert len(response.owner.display_name) < len(project.owner.display_name)
    assert (
        serialize_tool_success(outcome).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )


def _collaborator(*, hostile: str) -> ProjectCollaboratorResponse:
    collaborator = ProjectCollaboratorResponse(
        user_id=8,
        display_name="Collaborator",
        email="collaborator@example.com",
        is_owner=False,
        permissions=ProjectPermissionSet(
            edit_project=True,
            manage_papers=False,
            manage_collaborators=False,
        ),
        joined_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    collaborator.display_name = hostile
    collaborator.email = hostile
    return collaborator


def test_project_member_list_bounds_fifty_hostile_identity_rows() -> None:
    hostile = '\x00\\"🙂' * 100_000
    members = [_collaborator(hostile=hostile) for _ in range(50)]
    capabilities = MagicMock()
    capabilities.projects.members_page.return_value = ProjectCollaboratorListResponse(
        items=members,
        next_cursor="signed-member-continuation",
        total_count=100,
    )

    outcome = _handler().list_project_members(
        capabilities,
        _context(),
        ListProjectMembersInput(project_id=uuid4(), limit=50),
    )
    response = ProjectMemberListToolOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert len(response.items) == 50
    assert response.next_cursor == "signed-member-continuation"
    assert response.content_truncated is True
    assert all(
        item.email == f"truncated-user-{item.user_id}@example.com"
        for item in response.items
    )
    assert members[0].display_name == hostile
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES


@pytest.mark.parametrize("changed", [False, True])
def test_project_member_update_returns_compact_receipt_and_direct_lookup(
    changed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = '\x00\\"🙂' * 100_000
    member = _collaborator(hostile=hostile)
    project = _project(description="supported")
    capabilities = MagicMock()
    capabilities.projects.get.return_value = project
    capabilities.projects.member.return_value = member
    capabilities.projects.update_member.return_value = member
    handler = _handler()
    monkeypatch.setattr(handler, "_confirmation", MagicMock(return_value=None))
    requested = member.permissions.model_dump()
    if changed:
        requested["manage_papers"] = True

    outcome = handler.update_project_member(
        capabilities,
        _context(),
        UpdateProjectMemberInput(
            project_id=project.id,
            user_id=member.user_id,
            **requested,
        ),
    )
    completed = ConfirmationAwareAction.model_validate(outcome.payload).root
    serialized = serialize_tool_success(outcome)

    assert isinstance(completed, CompletedAction)
    assert completed.result == {
        "project_id": str(project.id),
        "user_id": member.user_id,
        "is_owner": False,
        "permissions": member.permissions.model_dump(mode="json"),
    }
    assert completed.changed is changed
    capabilities.projects.member.assert_called_once()
    capabilities.projects.members.assert_not_called()
    if changed:
        capabilities.projects.update_member.assert_called_once()
    else:
        capabilities.projects.update_member.assert_not_called()
    assert outcome.action is not None and outcome.action["result"] is None
    assert hostile not in serialized.text_content
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES


def test_project_ownership_transfer_returns_compact_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = '\x00\\"🙂' * 100_000
    project = _project(description=hostile)
    project.owner.display_name = hostile
    capabilities = MagicMock()
    capabilities.projects.plan_transfer.return_value = SimpleNamespace(
        state=SimpleNamespace(target_email="new-owner@example.com"),
        project_title=hostile,
        quota=SimpleNamespace(
            state=SimpleNamespace(
                project_document_count=1,
                active_reservation_count=0,
            )
        ),
    )
    capabilities.projects.transfer.return_value = project
    handler = _handler()
    monkeypatch.setattr(handler, "_confirmation", MagicMock(return_value=None))

    outcome = handler.transfer_project_ownership(
        capabilities,
        _context(),
        TransferProjectOwnershipInput(
            project_id=project.id,
            new_owner_id=8,
        ),
    )
    completed = ConfirmationAwareAction.model_validate(outcome.payload).root
    serialized = serialize_tool_success(outcome)

    assert isinstance(completed, CompletedAction)
    assert completed.result == {"project_id": str(project.id), "new_owner_id": 8}
    assert outcome.action is not None and outcome.action["result"] is None
    assert hostile not in serialized.text_content
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES


def test_project_member_remove_uses_direct_authorized_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(description="supported")
    member = _collaborator(hostile="Collaborator")
    capabilities = MagicMock()
    capabilities.projects.get.return_value = project
    capabilities.projects.member.return_value = member
    handler = _handler()
    monkeypatch.setattr(handler, "_confirmation", MagicMock(return_value=None))

    outcome = handler.remove_project_member(
        capabilities,
        _context(),
        RemoveProjectMemberInput(project_id=project.id, user_id=member.user_id),
    )

    capabilities.projects.member.assert_called_once()
    capabilities.projects.members.assert_not_called()
    capabilities.projects.remove_member.assert_called_once()
    assert serialize_tool_success(outcome).call_tool_result_utf8_bytes <= (
        DEFAULT_TOOL_OUTPUT_BYTES
    )


@pytest.mark.parametrize(
    ("action", "delivery_status"),
    [
        ("project_invitation_created", ProjectInvitationDeliveryStatus.PENDING),
        ("project_invitation_resent", ProjectInvitationDeliveryStatus.SENT),
    ],
)
def test_invitation_mutation_receipts_bound_historical_names(
    action: str,
    delivery_status: ProjectInvitationDeliveryStatus,
) -> None:
    hostile = '\x00\x01"\\🙂' * 100_000
    invitation = ProjectInvitationResponse(
        id=uuid4(),
        project_id=uuid4(),
        project_name=hostile,
        email="invitee@example.com",
        invited_by=hostile,
        permissions=ProjectPermissionSet(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=False,
        ),
        expires_at=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        delivery_status=delivery_status,
        delivered_at=None,
    )
    outcome = project_invitation_action(
        _handler()._completed(
            action=action,
            affected_resources=[
                f"project:{invitation.project_id}",
                f"invitation:{invitation.id}",
            ],
            result={
                "invitation": invitation.model_dump(mode="json"),
                "email_delivery": str(delivery_status),
            },
            guidance="Email delivery is queued.",
        )
    )

    completed = ConfirmationAwareAction.model_validate(outcome.payload).root
    assert completed.status == "completed"
    assert completed.result is not None
    assert completed.result["content_truncated"] is True
    assert outcome.action is not None
    assert outcome.action["result"] is None
    serialized = serialize_tool_success(outcome)
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES
    assert "\ufffd" not in serialized.text_content


@pytest.mark.parametrize("operation", ["remove_paper", "leave", "revoke"])
def test_confirmation_impacts_bound_historical_project_titles(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = '\x00\x01"\\🙂' * 100_000
    project = _project(description="supported")
    project.title = hostile
    capabilities = MagicMock()
    handler = _handler()
    confirmation = MagicMock(return_value=ToolOutcome(payload={}))
    monkeypatch.setattr(handler, "_confirmation", confirmation)

    if operation == "remove_paper":
        document_id = uuid4()
        capabilities.projects.plan_remove_document.return_value = SimpleNamespace(
            project_title=hostile,
            state=SimpleNamespace(
                annotation_thread_count=1,
                annotation_comment_count=2,
            ),
        )
        handler.remove_paper_from_project(
            capabilities,
            _context(),
            ProjectPaperInput(
                project_id=project.id,
                document_id=document_id,
            ),
        )
    elif operation == "leave":
        project.owner.id = 99
        capabilities.projects.get.return_value = project
        handler.leave_project(
            capabilities,
            _context(),
            LeaveProjectInput(project_id=project.id),
        )
    else:
        capabilities.projects.get.return_value = project
        invitation = ProjectInvitationResponse(
            id=uuid4(),
            project_id=project.id,
            project_name=hostile,
            email="invitee@example.com",
            invited_by="Owner",
            permissions=ProjectPermissionSet(),
            expires_at=datetime(2026, 8, 25, tzinfo=UTC),
            created_at=datetime(2026, 8, 24, tzinfo=UTC),
            delivery_status=ProjectInvitationDeliveryStatus.SENT,
            delivered_at=datetime(2026, 8, 24, tzinfo=UTC),
        )
        capabilities.projects.invitation.return_value = invitation
        handler.revoke_project_invitation(
            capabilities,
            _context(),
            InvitationInput(
                project_id=project.id,
                invitation_id=invitation.id,
            ),
        )

    impact = confirmation.call_args.kwargs["impact"]
    assert len(impact.summary) <= 1_000
    assert hostile not in impact.summary
