"""Cursor-paginated project activity projected from canonical shared facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast as typing_cast
from uuid import UUID

from sqlalchemy import String, and_, cast, literal, or_, select

from app.modules.identity.infrastructure.models import AuthUser
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document
from app.modules.projects.infrastructure.access import require_project_access
from app.modules.projects.infrastructure.models import (
    ProjectCollaborator,
    ProjectPaper,
)
from app.modules.reading_activity.application.contracts import (
    ProjectActivityKind,
    ProjectActivityItemResponse,
    ProjectActivityResponse,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    AnnotationThread,
    ResearchItem,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind


@dataclass(frozen=True, slots=True)
class _ActivityItem:
    id: str
    kind: ProjectActivityKind
    occurred_at: datetime
    actor_id: int | None = None
    document_id: UUID | None = None


class ProjectActivityRepository(ReadingActivityRepositoryBase):
    """Read a bounded merged feed without materializing duplicate activity rows."""

    def project_activity(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> ProjectActivityResponse:
        require_project_access(self._db, project_id=project_id, user_id=actor.id)
        if self._activity_cursors is None:
            raise RuntimeError("project_activity_cursors_not_configured")
        fingerprint = _activity_cursor_fingerprint(
            actor_id=actor.id,
            project_id=project_id,
        )
        cursor_key = (
            _parse_activity_cursor(
                typing_cast(
                    tuple[str, str],
                    self._activity_cursors.decode_keyset(
                        cursor=cursor,
                        fingerprint=fingerprint,
                        arity=2,
                    ),
                )
            )
            if cursor is not None
            else None
        )
        cursor_at = cursor_key[0] if cursor_key is not None else None
        cursor_id = cursor_key[1] if cursor_key is not None else None
        items: list[_ActivityItem] = []
        source_limit = limit + 1

        paper_statement = select(ProjectPaper).where(
            ProjectPaper.project_id == project_id
        )
        if cursor_at is not None and cursor_id is not None:
            paper_statement = paper_statement.where(
                _activity_before_cursor(
                    ProjectPaper.created_at,
                    literal("paper:") + cast(ProjectPaper.id, String),
                    cursor_at,
                    cursor_id,
                )
            )
        papers = self._db.scalars(
            paper_statement.order_by(
                ProjectPaper.created_at.desc(), ProjectPaper.id.desc()
            ).limit(source_limit)
        ).all()
        items.extend(
            _ActivityItem(
                id=f"paper:{paper.id}",
                kind=ProjectActivityKind.PAPER_ADDED,
                occurred_at=paper.created_at,
                actor_id=paper.added_by_id,
                document_id=paper.document_id,
            )
            for paper in papers
        )

        collaborator_statement = select(ProjectCollaborator).where(
            ProjectCollaborator.project_id == project_id
        )
        if cursor_at is not None and cursor_id is not None:
            collaborator_statement = collaborator_statement.where(
                _activity_before_cursor(
                    ProjectCollaborator.joined_at,
                    literal("member:") + cast(ProjectCollaborator.id, String),
                    cursor_at,
                    cursor_id,
                )
            )
        collaborators = self._db.scalars(
            collaborator_statement.order_by(
                ProjectCollaborator.joined_at.desc(),
                ProjectCollaborator.id.desc(),
            ).limit(source_limit)
        ).all()
        items.extend(
            _ActivityItem(
                id=f"member:{collaborator.id}",
                kind=ProjectActivityKind.MEMBER_JOINED,
                occurred_at=collaborator.joined_at,
                actor_id=collaborator.user_id,
            )
            for collaborator in collaborators
        )

        research_statement = select(ResearchItem).where(
            ResearchItem.audience_project_id == project_id,
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
        )
        if cursor_at is not None and cursor_id is not None:
            research_statement = research_statement.where(
                _activity_before_cursor(
                    ResearchItem.created_at,
                    literal("research:") + cast(ResearchItem.id, String),
                    cursor_at,
                    cursor_id,
                )
            )
        research_items = self._db.scalars(
            research_statement.order_by(
                ResearchItem.created_at.desc(), ResearchItem.id.desc()
            ).limit(source_limit)
        ).all()
        items.extend(
            _ActivityItem(
                id=f"research:{item.id}",
                kind=(
                    ProjectActivityKind.ANNOTATION_CREATED
                    if item.kind == ResearchItemKind.ANNOTATION_THREAD.value
                    else ProjectActivityKind.OUTPUT_CREATED
                ),
                occurred_at=item.created_at,
                actor_id=item.created_by_id,
                document_id=item.target_document_id or item.audience_document_id,
            )
            for item in research_items
        )

        comment_statement = (
            select(AnnotationComment, ResearchItem.target_document_id)
            .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
            .where(ResearchItem.audience_project_id == project_id)
        )
        if cursor_at is not None and cursor_id is not None:
            comment_statement = comment_statement.where(
                _activity_before_cursor(
                    AnnotationComment.created_at,
                    literal("comment:") + cast(AnnotationComment.id, String),
                    cursor_at,
                    cursor_id,
                )
            )
        comments = self._db.execute(
            comment_statement.order_by(
                AnnotationComment.created_at.desc(), AnnotationComment.id.desc()
            ).limit(source_limit)
        ).all()
        items.extend(
            _ActivityItem(
                id=f"comment:{comment.id}",
                kind=ProjectActivityKind.DISCUSSION_MESSAGE_POSTED,
                occurred_at=comment.created_at,
                actor_id=comment.created_by_id,
                document_id=document_id,
            )
            for comment, document_id in comments
        )

        resolved_statement = (
            select(AnnotationThread, ResearchItem.target_document_id)
            .join(ResearchItem, ResearchItem.id == AnnotationThread.research_item_id)
            .where(
                ResearchItem.audience_project_id == project_id,
                AnnotationThread.resolved_at.is_not(None),
            )
        )
        if cursor_at is not None and cursor_id is not None:
            resolved_statement = resolved_statement.where(
                _activity_before_cursor(
                    AnnotationThread.resolved_at,
                    literal("resolved:")
                    + cast(AnnotationThread.research_item_id, String),
                    cursor_at,
                    cursor_id,
                )
            )
        resolved = self._db.execute(
            resolved_statement.order_by(
                AnnotationThread.resolved_at.desc(),
                AnnotationThread.research_item_id.desc(),
            ).limit(source_limit)
        ).all()
        for thread, document_id in resolved:
            assert thread.resolved_at is not None
            items.append(
                _ActivityItem(
                    id=f"resolved:{thread.research_item_id}",
                    kind=ProjectActivityKind.DISCUSSION_RESOLVED,
                    occurred_at=thread.resolved_at,
                    actor_id=thread.resolved_by_id,
                    document_id=document_id,
                )
            )

        page, has_more = _page_activity_items(
            items,
            limit=limit,
            cursor_key=cursor_key,
        )
        actor_names = self._actor_names(page)
        document_titles = self._document_titles(page, actor_id=actor.id)
        response_items = [
            _activity_response_item(
                item,
                actor_names=actor_names,
                document_titles=document_titles,
            )
            for item in page
        ]
        return ProjectActivityResponse(
            project_id=project_id,
            items=response_items,
            next_cursor=(
                self._activity_cursors.encode_keyset(
                    fingerprint=fingerprint,
                    values=(
                        _activity_item_key(page[-1])[0].isoformat(),
                        _activity_item_key(page[-1])[1],
                    ),
                )
                if has_more and page
                else None
            ),
        )

    def _actor_names(self, items: list[_ActivityItem]) -> dict[int, str]:
        user_ids = {item.actor_id for item in items if item.actor_id is not None}
        if not user_ids:
            return {}
        return {
            user.id: user.display_name or user.email
            for user in self._db.scalars(
                select(AuthUser).where(AuthUser.id.in_(user_ids))
            ).all()
        }

    def _document_titles(
        self,
        items: list[_ActivityItem],
        *,
        actor_id: int,
    ) -> dict[UUID, str | None]:
        document_ids = {
            item.document_id for item in items if item.document_id is not None
        }
        if not document_ids:
            return {}
        return {
            document_id: title
            for document_id, title in self._db.execute(
                select(Document.id, Document.title).where(
                    Document.id.in_(document_ids),
                    accessible_document_condition(user_id=actor_id),
                )
            ).all()
        }


def _activity_item_key(item: _ActivityItem) -> tuple[datetime, str]:
    return (item.occurred_at, item.id)


def _activity_document_destination(
    item: _ActivityItem,
    document_titles: dict[UUID, str | None],
) -> tuple[UUID | None, str | None]:
    if item.document_id is None or item.document_id not in document_titles:
        return (None, None)
    return (item.document_id, document_titles[item.document_id])


def _activity_response_item(
    item: _ActivityItem,
    *,
    actor_names: dict[int, str],
    document_titles: dict[UUID, str | None],
) -> ProjectActivityItemResponse:
    document_id, document_title = _activity_document_destination(
        item,
        document_titles,
    )
    return ProjectActivityItemResponse(
        id=item.id,
        kind=item.kind,
        occurred_at=item.occurred_at,
        actor_display_name=(
            actor_names.get(item.actor_id) if item.actor_id is not None else None
        ),
        document_id=document_id,
        document_title=document_title,
    )


def _page_activity_items(
    items: list[_ActivityItem],
    *,
    limit: int,
    cursor_key: tuple[datetime, str] | None,
) -> tuple[list[_ActivityItem], bool]:
    ordered = sorted(items, key=_activity_item_key, reverse=True)
    if cursor_key is not None:
        ordered = [item for item in ordered if _activity_item_key(item) < cursor_key]
    return (ordered[:limit], len(ordered) > limit)


def _activity_before_cursor(
    occurred_at_column: Any,
    id_expression: Any,
    cursor_at: datetime,
    cursor_id: str,
) -> Any:
    return or_(
        occurred_at_column < cursor_at,
        and_(occurred_at_column == cursor_at, id_expression < cursor_id),
    )


def _parse_activity_cursor(values: tuple[str, str]) -> tuple[datetime, str]:
    try:
        occurred_at = datetime.fromisoformat(values[0])
        item_id = values[1]
        if occurred_at.tzinfo is None or not item_id:
            raise ValueError
    except ValueError as exc:
        raise AppError(
            code="project_activity_cursor_invalid",
            message="The project activity cursor is invalid",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from exc
    return (occurred_at, item_id)


def _activity_cursor_fingerprint(*, actor_id: int, project_id: UUID) -> str:
    return f"actor={actor_id};project={project_id}"


__all__ = ["ProjectActivityRepository"]
