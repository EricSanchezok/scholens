"""Typed Project response assembly for SQLAlchemy adapters."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.database.models import (
    AuthUser,
    Conversation,
    Project,
    ProjectCollaborator,
    ProjectPaper,
    ResearchItem,
    ResearchAudienceType,
)
from app.modules.projects.infrastructure.access import ProjectAccess
from app.bootstrap.adapters.project_repository import project_repository
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPermissionSet,
    ProjectResponse,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _permissions(access: ProjectAccess) -> ProjectPermissionSet:
    return ProjectPermissionSet(
        edit_project=access.permissions.edit_project,
        manage_papers=access.permissions.manage_papers,
        manage_collaborators=access.permissions.manage_collaborators,
    )


def _project_counts(
    db: Session,
    *,
    project_id: uuid.UUID,
    current_user_id: int,
) -> tuple[int, int, int, int]:
    statements = (
        select(func.count(ProjectPaper.id)).where(
            ProjectPaper.project_id == project_id
        ),
        select(func.count(Conversation.id)).where(
            Conversation.scope_type == "project",
            Conversation.project_id == project_id,
            Conversation.user_id == current_user_id,
        ),
        select(func.count(ResearchItem.id)).where(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project_id,
        ),
        select(func.count(ProjectCollaborator.id)).where(
            ProjectCollaborator.project_id == project_id
        ),
    )
    counts = [int(db.scalar(statement) or 0) for statement in statements]
    return counts[0], counts[1], counts[2], counts[3]


def _project_activity(
    db: Session,
    *,
    project: Project,
    current_user_id: int,
) -> datetime:
    candidates = (
        db.scalar(
            select(func.max(ProjectPaper.created_at)).where(
                ProjectPaper.project_id == project.id
            )
        ),
        db.scalar(
            select(func.max(Conversation.updated_at)).where(
                Conversation.scope_type == "project",
                Conversation.project_id == project.id,
                Conversation.user_id == current_user_id,
            )
        ),
        db.scalar(
            select(func.max(ResearchItem.updated_at)).where(
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                ResearchItem.audience_project_id == project.id,
            )
        ),
    )
    return max((project.updated_at, *(value for value in candidates if value)))


def project_response(
    db: Session,
    *,
    project: Project,
    current_user_id: int,
) -> ProjectResponse:
    access = project_repository.get_access(
        db,
        project_id=project.id,
        user_id=current_user_id,
    )
    owner = db.get(AuthUser, project.owner_id)
    if owner is None:
        raise RuntimeError("project_owner_missing")
    (
        num_papers,
        num_conversations,
        num_outputs,
        num_collaborators,
    ) = _project_counts(
        db,
        project_id=project.id,
        current_user_id=current_user_id,
    )
    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        owner=ProjectOwnerResponse(
            id=owner.id,
            display_name=owner.display_name or owner.email,
            email=owner.email,
        ),
        membership=ProjectMembershipResponse(
            kind="owner" if access.is_owner else "collaborator",
            permissions=_permissions(access),
        ),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=access.can_edit_project,
            manage_papers=access.can_manage_papers,
            manage_collaborators=access.can_manage_collaborators,
            transfer=access.is_owner,
            delete=access.is_owner,
            leave=not access.is_owner,
        ),
        num_papers=num_papers,
        num_conversations=num_conversations,
        num_outputs=num_outputs,
        num_collaborators=num_collaborators,
        activity_at=_project_activity(
            db,
            project=project,
            current_user_id=current_user_id,
        ),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
