"""Project collaboration responses enriched with authorized profile avatars."""

from app.modules.projects.application.contracts import ProjectCollaboratorResponse
from app.shared.application import AvatarReference
from pydantic import BaseModel


class AvatarProjectCollaboratorResponse(ProjectCollaboratorResponse):
    avatar: AvatarReference | None = None


class AvatarProjectCollaboratorListResponse(BaseModel):
    items: list[AvatarProjectCollaboratorResponse]
    next_cursor: str | None = None


__all__ = [
    "AvatarProjectCollaboratorListResponse",
    "AvatarProjectCollaboratorResponse",
]
