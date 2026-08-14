"""Cross-module authorization policy for every Research-item audience."""

from __future__ import annotations

from app.database.models import (
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
    ResearchItem,
    ResearchAudienceType,
)
from app.modules.research.domain import (
    ResearchAccessDecision,
    ResearchAccessFacts,
    evaluate_research_access,
    require_research_manager,
    require_research_visible,
)
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement


def research_item_visible_to(user_id: int) -> ColumnElement[bool]:
    """Return the complete SQL audience predicate for a Research item."""
    target_document_access = exists(
        select(LibraryPaper.id).where(
            LibraryPaper.document_id == ResearchItem.target_document_id,
            LibraryPaper.user_id == user_id,
        )
    )
    target_project_access = exists(
        select(ProjectPaper.id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            ProjectPaper.document_id == ResearchItem.target_document_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    document_access = exists(
        select(LibraryPaper.id).where(
            LibraryPaper.document_id == ResearchItem.audience_document_id,
            LibraryPaper.user_id == user_id,
        )
    )
    project_document_access = exists(
        select(ProjectPaper.id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            ProjectPaper.document_id == ResearchItem.audience_document_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    project_access = exists(
        select(Project.id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            Project.id == ResearchItem.audience_project_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    return or_(
        and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
            or_(
                ResearchItem.target_document_id.is_(None),
                target_document_access,
                target_project_access,
            ),
        ),
        and_(
            ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
            or_(document_access, project_document_access),
        ),
        and_(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            project_access,
        ),
    )


class ResearchItemPolicy:
    def evaluate(
        self, db: Session, *, item: ResearchItem, user_id: int
    ) -> ResearchAccessDecision:
        is_creator = item.created_by_id == user_id
        audience_type = ResearchAudienceType(item.audience_type)
        can_edit_project = False
        if audience_type is ResearchAudienceType.DOCUMENT:
            has_access = item.audience_document_id is not None and (
                get_document_access(
                    db, document_id=item.audience_document_id, user_id=user_id
                )
                is not None
            )
        elif audience_type is ResearchAudienceType.PROJECT:
            project_access = (
                get_project_access(
                    db, project_id=item.audience_project_id, user_id=user_id
                )
                if item.audience_project_id is not None
                else None
            )
            has_access = project_access is not None
            can_edit_project = bool(project_access and project_access.can_edit_project)
        else:
            has_access = is_creator and (
                item.target_document_id is None
                or get_document_access(
                    db, document_id=item.target_document_id, user_id=user_id
                )
                is not None
            )
        return evaluate_research_access(
            ResearchAccessFacts(
                audience_type=audience_type,
                is_creator=is_creator,
                has_audience_access=has_access,
                can_edit_project=can_edit_project,
            )
        )

    def require_visible(
        self, db: Session, *, item: ResearchItem, user_id: int
    ) -> ResearchAccessDecision:
        access = self.evaluate(db, item=item, user_id=user_id)
        require_research_visible(access)
        return access

    def require_creator_manager(
        self, db: Session, *, item: ResearchItem, user_id: int
    ) -> ResearchAccessDecision:
        access = self.require_visible(db, item=item, user_id=user_id)
        require_research_manager(access)
        return access


research_item_policy = ResearchItemPolicy()

__all__ = ["research_item_policy", "research_item_visible_to"]
