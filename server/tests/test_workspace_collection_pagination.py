from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.bootstrap.adapters.project_repository import project_repository
from app.modules.action_confirmations.contracts import ConfirmationChallenge
from app.modules.papers.application.contracts.tags import (
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.modules.papers.application.tags import (
    LibraryTagGateway,
    LibraryTagPage,
    LibraryTagPagePosition,
    LibraryTags,
)
from app.modules.papers.infrastructure.tag_repository import LibraryTagRepository
from app.modules.projects.application.contracts import (
    ProjectInvitationDeliveryStatus,
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
    ProjectPermissionSet,
)
from app.modules.projects.application.projects import (
    ProjectInvitationPage,
    ProjectInvitationPagePosition,
    Projects,
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
from app.tooling import ToolOutcome, serialize_tool_success
from app.tooling.contracts import DEFAULT_TOOL_OUTPUT_BYTES, ToolExecutionContext
from app.tooling.workspace_collection_projection import (
    project_invitation_list,
    project_library_tag_list,
)
from app.tooling.workspace_contracts import (
    DeleteLibraryTagInput,
    LibraryTagListOutput,
    ListLibraryTagsInput,
    ListProjectInvitationsInput,
    ProjectInvitationListOutput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _tool_context() -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(),
        operation=operation,
        paper_collection=MagicMock(),
        anchor_document_id=None,
        invocation_id="library-tag-preview-budget-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="library-tag-preview-budget-secret",
    )


def _projects(gateway: MagicMock) -> Projects:
    return Projects(
        gateway=gateway,
        capacity=MagicMock(),
        signer=MagicMock(),
        cursors=SignedCursorCodec(
            "project-invitation-pagination-test-secret",
            revision="projects-v1",
            error_code="project_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=MagicMock(),
    )


def _invitation_page(*, invitation_id: UUID, has_more: bool) -> ProjectInvitationPage:
    return ProjectInvitationPage(
        items=[ProjectInvitationResponse.model_construct(id=invitation_id)],
        positions=[ProjectInvitationPagePosition(created_at=NOW, id=invitation_id)],
        has_more=has_more,
    )


def _library_tags(gateway: MagicMock) -> LibraryTags:
    return LibraryTags(
        gateway,
        cursors=SignedCursorCodec(
            "library-tag-pagination-test-secret",
            revision="library-tags-v1",
            error_code="library_tag_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=MagicMock(),
    )


def _tag_page(*, tag_id: UUID, name: str, has_more: bool) -> LibraryTagPage:
    return LibraryTagPage(
        items=[LibraryTagResponse(id=tag_id, name=name, color=None)],
        positions=[LibraryTagPagePosition(name=name.casefold(), id=tag_id)],
        has_more=has_more,
    )


def _tamper(cursor: str) -> str:
    replacement = "A" if cursor[-1] != "A" else "B"
    return f"{cursor[:-1]}{replacement}"


def test_new_collection_inputs_preserve_legacy_minimal_requests() -> None:
    project_id = uuid4()

    invitations = ListProjectInvitationsInput.model_validate(
        {"project_id": str(project_id)}
    )
    tags = ListLibraryTagsInput.model_validate({})

    assert invitations.project_id == project_id
    assert invitations.cursor is None
    assert invitations.limit == 20
    assert tags.cursor is None
    assert tags.limit == 20


def test_project_invitation_pages_close_and_allow_page_size_changes() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_invitations_page.side_effect = [
        _invitation_page(invitation_id=first_id, has_more=True),
        _invitation_page(invitation_id=second_id, has_more=False),
    ]
    projects = _projects(gateway)
    project_id = uuid4()

    first = projects.invitations_page(actor=_actor(), project_id=project_id, limit=1)
    assert first.next_cursor is not None

    second = projects.invitations_page(
        actor=_actor(),
        project_id=project_id,
        cursor=first.next_cursor,
        limit=20,
    )

    assert second.next_cursor is None
    assert gateway.list_invitations_page.call_args_list[1].kwargs["limit"] == 20
    assert gateway.list_invitations_page.call_args_list[1].kwargs["position"] == (
        ProjectInvitationPagePosition(created_at=NOW, id=first_id)
    )


@pytest.mark.parametrize("binding_change", ["actor", "project", "tamper"])
def test_project_invitation_cursor_rejects_tamper_and_cross_scope_reuse(
    binding_change: str,
) -> None:
    gateway = MagicMock()
    gateway.list_invitations_page.return_value = _invitation_page(
        invitation_id=uuid4(),
        has_more=True,
    )
    projects = _projects(gateway)
    project_id = uuid4()
    first = projects.invitations_page(actor=_actor(), project_id=project_id, limit=1)
    assert first.next_cursor is not None

    cursor = (
        _tamper(first.next_cursor) if binding_change == "tamper" else first.next_cursor
    )
    actor = _actor(8) if binding_change == "actor" else _actor()
    requested_project_id = uuid4() if binding_change == "project" else project_id
    with pytest.raises(AppError) as raised:
        projects.invitations_page(
            actor=actor,
            project_id=requested_project_id,
            cursor=cursor,
            limit=20,
        )

    assert raised.value.code == "project_cursor_invalid"


def test_project_invitation_repository_uses_descending_keyset_and_limit_plus_one() -> (
    None
):
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = []
    project_id = uuid4()
    position_id = uuid4()

    with patch(
        "app.bootstrap.adapters.project_repository.require_project_permission"
    ) as require_permission:
        rows = project_repository.list_project_invitations_page(
            db,
            project_id=project_id,
            actor_id=7,
            limit=20,
            position_created_at=NOW,
            position_id=position_id,
        )

    assert rows == []
    require_permission.assert_called_once_with(
        db,
        project_id=project_id,
        user_id=7,
        permission="manage_collaborators",
    )
    statement = str(
        db.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "project_invitations.created_at <" in statement
    assert "project_invitations.id <" in statement
    assert "ORDER BY scholens.project_invitations.created_at DESC" in statement
    assert "scholens.project_invitations.id DESC" in statement
    assert "LIMIT 21" in statement


def test_library_tag_pages_close_and_allow_page_size_changes() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock(spec=LibraryTagGateway)
    gateway.list_page.side_effect = [
        _tag_page(tag_id=first_id, name="Alpha", has_more=True),
        _tag_page(tag_id=second_id, name="Beta", has_more=False),
    ]
    tags = _library_tags(gateway)

    first = tags.list_page(actor=_actor(), limit=1)
    assert first.next_cursor is not None

    second = tags.list_page(actor=_actor(), cursor=first.next_cursor, limit=50)

    assert second.next_cursor is None
    assert gateway.list_page.call_args_list[1].kwargs["limit"] == 50
    assert gateway.list_page.call_args_list[1].kwargs["position"] == (
        LibraryTagPagePosition(name="alpha", id=first_id)
    )


@pytest.mark.parametrize("binding_change", ["actor", "tamper"])
def test_library_tag_cursor_rejects_tamper_and_cross_actor_reuse(
    binding_change: str,
) -> None:
    gateway = MagicMock(spec=LibraryTagGateway)
    gateway.list_page.return_value = _tag_page(
        tag_id=uuid4(),
        name="Alpha",
        has_more=True,
    )
    tags = _library_tags(gateway)
    first = tags.list_page(actor=_actor(), limit=1)
    assert first.next_cursor is not None

    cursor = (
        _tamper(first.next_cursor) if binding_change == "tamper" else first.next_cursor
    )
    actor = _actor(8) if binding_change == "actor" else _actor()
    with pytest.raises(AppError) as raised:
        tags.list_page(actor=actor, cursor=cursor, limit=50)

    assert raised.value.code == "library_tag_cursor_invalid"


def test_library_tag_repository_uses_owner_keyset_and_limit_plus_one() -> None:
    db = MagicMock(spec=Session)
    db.execute.return_value.tuples.return_value.all.return_value = []
    position_id = uuid4()

    rows = LibraryTagRepository.list_owned_page(
        db,
        user_id=7,
        limit=50,
        position_name="alpha",
        position_id=position_id,
    )

    assert rows == []
    statement = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "paper_tags.user_id = 7" in statement
    assert "lower(scholens.paper_tags.name) > 'alpha'" in statement
    assert "paper_tags.id >" in statement
    assert "ORDER BY lower(scholens.paper_tags.name) ASC" in statement
    assert "scholens.paper_tags.id ASC" in statement
    assert "LIMIT 51" in statement


def test_max_collection_pages_fit_the_real_call_tool_result_budget() -> None:
    hostile = '\x00\x01"\\🙂' * 100_000
    invitations = ProjectInvitationListResponse(
        items=[
            ProjectInvitationResponse(
                id=uuid4(),
                project_id=uuid4(),
                project_name=hostile,
                email=f"researcher-{index:02d}@example.com",
                invited_by=hostile,
                permissions=ProjectPermissionSet(
                    edit_project=True,
                    manage_papers=True,
                    manage_collaborators=True,
                ),
                expires_at=NOW,
                created_at=NOW,
                delivery_status=ProjectInvitationDeliveryStatus.PENDING,
                delivered_at=None,
            )
            for index in range(20)
        ],
        next_cursor="c" * 512,
    )
    tags = LibraryTagListResponse(
        items=[
            LibraryTagResponse(
                id=uuid4(),
                name=hostile,
                color=hostile,
            )
            for _ in range(50)
        ],
        next_cursor="c" * 512,
    )

    invitation_outcome = project_invitation_list(
        ToolOutcome(payload=invitations.model_dump(mode="json"))
    )
    tag_outcome = project_library_tag_list(
        ToolOutcome(payload=tags.model_dump(mode="json"))
    )

    assert (
        ProjectInvitationListOutput.model_validate(
            invitation_outcome.payload
        ).content_truncated
        is True
    )
    assert (
        LibraryTagListOutput.model_validate(tag_outcome.payload).content_truncated
        is True
    )
    for outcome in (invitation_outcome, tag_outcome):
        serialized = serialize_tool_success(outcome)
        assert serialized.call_tool_result_utf8_bytes < 200_000
        assert "\ufffd" not in serialized.text_content


def test_delete_tag_preview_bounds_hostile_historical_name_in_real_envelope() -> None:
    tag_id = uuid4()
    hostile = '\x00\x01"\\🙂' * 100_000
    capabilities = MagicMock()
    capabilities.library_tags.get.return_value = LibraryTagResponse(
        id=tag_id,
        name=hostile,
        color=None,
    )

    def issue_confirmation(**arguments: object) -> ConfirmationChallenge:
        return ConfirmationChallenge.model_validate(
            {
                "confirmation_token": "x" * 32,
                "expires_at": NOW,
                "impact": arguments["impact"],
            }
        )

    capabilities.action_confirmations.issue.side_effect = issue_confirmation

    outcome = _handler().delete_library_tag(
        capabilities,
        _tool_context(),
        DeleteLibraryTagInput(tag_id=tag_id),
    )

    challenge = ConfirmationChallenge.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert challenge.impact.summary.endswith("…'.")
    assert len(challenge.impact.summary) < len(hostile)
    assert serialized.call_tool_result_utf8_bytes <= DEFAULT_TOOL_OUTPUT_BYTES
    assert "\ufffd" not in serialized.text_content
    capabilities.library_tags.delete.assert_not_called()
