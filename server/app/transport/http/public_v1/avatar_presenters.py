"""Attach shared avatars only after the owning query authorizes its records."""

from __future__ import annotations

import logging

from app.modules.identity.application import (
    SharedAvatarReader,
    SharedAvatarUnavailableError,
)
from app.modules.projects.application.avatar_contracts import (
    AvatarProjectCollaboratorListResponse,
    AvatarProjectCollaboratorResponse,
)
from app.modules.projects.application.contracts import ProjectCollaboratorListResponse
from app.modules.research.application.avatar_contracts import (
    AvatarAnnotationCommentResponse,
    AvatarAnnotationThreadListResponse,
    AvatarAnnotationThreadSummaryResponse,
    AvatarResearchCreatorResponse,
)
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadListResponse,
    ResearchCreatorResponse,
)
from app.shared.application import AvatarReference

logger = logging.getLogger(__name__)


async def _read_visible_avatars(
    reader: SharedAvatarReader,
    user_ids: set[int],
) -> dict[int, AvatarReference]:
    try:
        return await reader.get_many(user_ids)
    except SharedAvatarUnavailableError:
        logger.warning(
            "shared_avatar_batch_unavailable",
            extra={"visible_user_count": len(user_ids)},
            exc_info=True,
        )
        return {}


async def present_project_collaborators(
    response: ProjectCollaboratorListResponse,
    reader: SharedAvatarReader,
) -> AvatarProjectCollaboratorListResponse:
    avatars = await _read_visible_avatars(
        reader,
        {member.user_id for member in response.items},
    )
    return AvatarProjectCollaboratorListResponse(
        items=[
            AvatarProjectCollaboratorResponse(
                **member.model_dump(),
                avatar=avatars.get(member.user_id),
            )
            for member in response.items
        ],
        next_cursor=response.next_cursor,
    )


def _present_creator(
    creator: ResearchCreatorResponse,
    avatars: dict[int, AvatarReference],
) -> AvatarResearchCreatorResponse:
    return AvatarResearchCreatorResponse(
        **creator.model_dump(),
        avatar=avatars.get(creator.id) if creator.id is not None else None,
    )


def _present_comment(
    comment: AnnotationCommentResponse,
    avatars: dict[int, AvatarReference],
) -> AvatarAnnotationCommentResponse:
    return AvatarAnnotationCommentResponse(
        **comment.model_dump(exclude={"created_by"}),
        created_by=_present_creator(comment.created_by, avatars),
    )


async def present_annotation_threads(
    response: AnnotationThreadListResponse,
    reader: SharedAvatarReader,
) -> AvatarAnnotationThreadListResponse:
    creators = {
        creator.id
        for item in response.items
        for creator in (
            item.created_by,
            item.resolved_by,
            *(comment.created_by for comment in item.comments),
        )
        if creator is not None and creator.id is not None
    }
    avatars = await _read_visible_avatars(reader, creators)
    return AvatarAnnotationThreadListResponse(
        items=[
            AvatarAnnotationThreadSummaryResponse(
                **item.model_dump(exclude={"created_by", "resolved_by", "comments"}),
                created_by=_present_creator(item.created_by, avatars),
                resolved_by=(
                    _present_creator(item.resolved_by, avatars)
                    if item.resolved_by is not None
                    else None
                ),
                comments=[
                    _present_comment(comment, avatars) for comment in item.comments
                ],
            )
            for item in response.items
        ],
        next_cursor=response.next_cursor,
    )


__all__ = ["present_annotation_threads", "present_project_collaborators"]
