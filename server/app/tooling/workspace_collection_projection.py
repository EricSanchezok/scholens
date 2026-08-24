"""Bounded projections for invitation and personal-tag collection tools."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from app.modules.papers.application.contracts.tags import (
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.modules.projects.application.contracts import (
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
)
from app.shared.domain import JsonValue
from app.tooling import workspace_contracts as wc
from app.tooling.bounded_projection import (
    bounded_optional_text as _optional_text,
    bounded_text as _text,
)
from app.tooling.contracts import ToolOutcome
from pydantic import ValidationError

INVITATION_TEXT_JSON_BYTES = 512
TAG_TEXT_JSON_BYTES = 256
INVITATION_LIST_GUIDANCE = (
    "Project and inviter names are bounded previews when content_truncated is true. "
    "Continue with next_cursor for every active invitation; invitation and Project "
    "UUIDs remain authoritative for follow-up actions."
)
TAG_LIST_GUIDANCE = (
    "Tag names and colors are bounded previews when content_truncated is true. "
    "Continue with next_cursor for every personal tag; tag UUIDs remain authoritative "
    "for assignment and update operations."
)
INVITATION_ACTION_GUIDANCE = (
    "Invitation names are bounded previews in this receipt. Use "
    "list_project_invitations with the Project UUID for current delivery state and "
    "the authoritative invitation UUID."
)


def _invitation(
    value: ProjectInvitationResponse,
) -> tuple[wc.ProjectInvitationToolResponse, bool]:
    project_name, project_name_truncated = _text(
        value.project_name,
        max_bytes=INVITATION_TEXT_JSON_BYTES,
    )
    invited_by, invited_by_truncated = _text(
        value.invited_by,
        max_bytes=INVITATION_TEXT_JSON_BYTES,
    )
    return (
        wc.ProjectInvitationToolResponse.model_validate(
            {
                **value.model_dump(mode="python"),
                "project_name": project_name,
                "invited_by": invited_by,
            }
        ),
        project_name_truncated or invited_by_truncated,
    )


def project_invitation_list(outcome: ToolOutcome) -> ToolOutcome:
    value = ProjectInvitationListResponse.model_validate(outcome.payload)
    items: list[wc.ProjectInvitationToolResponse] = []
    content_truncated = bool(outcome.artifacts) or outcome.action is not None
    for item in value.items:
        projected, item_truncated = _invitation(item)
        items.append(projected)
        content_truncated = content_truncated or item_truncated
    if isinstance(outcome.payload, dict):
        content_truncated = (
            content_truncated or outcome.payload.get("content_truncated") is True
        )
    payload = wc.ProjectInvitationListOutput(
        items=items,
        next_cursor=value.next_cursor,
        content_truncated=content_truncated,
        guidance=INVITATION_LIST_GUIDANCE,
    )
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        artifacts=[],
        action=None,
    )


def _tag(value: LibraryTagResponse) -> tuple[wc.LibraryTagToolResponse, bool]:
    name, name_truncated = _text(value.name, max_bytes=TAG_TEXT_JSON_BYTES)
    color, color_truncated = _optional_text(
        value.color,
        max_bytes=TAG_TEXT_JSON_BYTES,
    )
    return (
        wc.LibraryTagToolResponse(id=value.id, name=name, color=color),
        name_truncated or color_truncated,
    )


def project_library_tag_list(outcome: ToolOutcome) -> ToolOutcome:
    value = LibraryTagListResponse.model_validate(outcome.payload)
    items: list[wc.LibraryTagToolResponse] = []
    content_truncated = bool(outcome.artifacts) or outcome.action is not None
    for item in value.items:
        projected, item_truncated = _tag(item)
        items.append(projected)
        content_truncated = content_truncated or item_truncated
    if isinstance(outcome.payload, dict):
        content_truncated = (
            content_truncated or outcome.payload.get("content_truncated") is True
        )
    payload = wc.LibraryTagListOutput(
        items=items,
        next_cursor=value.next_cursor,
        content_truncated=content_truncated,
        guidance=TAG_LIST_GUIDANCE,
    )
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        artifacts=[],
        action=None,
    )


def project_invitation_action(outcome: ToolOutcome) -> ToolOutcome:
    """Project completed invitation receipts; leave confirmation previews intact."""

    try:
        completed = wc.CompletedAction.model_validate(outcome.payload)
    except ValidationError:
        return outcome
    result = dict(completed.result or {})
    raw_invitation = result.get("invitation")
    if not isinstance(raw_invitation, dict):
        return outcome
    invitation = ProjectInvitationResponse.model_validate(raw_invitation)
    projected, invitation_truncated = _invitation(invitation)
    prior_truncated = result.get("content_truncated") is True
    content_truncated = (
        prior_truncated or invitation_truncated or bool(outcome.artifacts)
    )
    result["invitation"] = cast(JsonValue, projected.model_dump(mode="json"))
    result["content_truncated"] = content_truncated
    guidance = INVITATION_ACTION_GUIDANCE if content_truncated else completed.guidance
    payload = completed.model_copy(update={"result": result, "guidance": guidance})
    action = payload.model_copy(update={"result": None})
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        artifacts=[],
        action=cast(dict[str, JsonValue], action.model_dump(mode="json")),
    )


__all__ = [
    "INVITATION_ACTION_GUIDANCE",
    "INVITATION_LIST_GUIDANCE",
    "TAG_LIST_GUIDANCE",
    "project_invitation_action",
    "project_invitation_list",
    "project_library_tag_list",
]
