"""SQLAlchemy adapter for annotation-thread search."""

from __future__ import annotations

from app.modules.research.application.search import (
    ResearchSearchComment,
    ResearchSearchQuery,
    ResearchSearchResponse,
    ResearchSearchResult,
)
from app.modules.research.application.positions import ResearchPosition
from pydantic import TypeAdapter
from app.bootstrap.adapters.research_access import research_item_visible_to
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    AnnotationThread,
    ResearchItem,
)
from app.shared.application import Actor
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload


class SqlResearchSearch:
    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        actor: Actor,
        request: ResearchSearchQuery,
    ) -> ResearchSearchResponse:
        pattern = f"%{request.query.casefold()}%"
        matching_comment = exists(
            select(AnnotationComment.id).where(
                AnnotationComment.thread_id == AnnotationThread.research_item_id,
                func.lower(AnnotationComment.content).like(pattern),
            )
        )
        statement = (
            select(ResearchItem)
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .where(
                research_item_visible_to(actor.id),
                or_(
                    func.lower(AnnotationThread.quote_text).like(pattern),
                    matching_comment,
                ),
            )
            .options(
                joinedload(ResearchItem.target_document),
                joinedload(ResearchItem.annotation_thread).selectinload(
                    AnnotationThread.comments
                ),
            )
            .order_by(ResearchItem.created_at.desc(), ResearchItem.id)
        )
        total = int(
            self._db.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = self._db.scalars(
            statement.offset(request.offset).limit(request.limit)
        ).all()
        items: list[ResearchSearchResult] = []
        for item in rows:
            thread = item.annotation_thread
            if thread is None or item.target_document_id is None:
                continue
            comments = [
                ResearchSearchComment(
                    id=comment.id,
                    content=comment.content,
                    role=comment.role,
                    created_at=comment.created_at,
                )
                for comment in thread.comments
                if request.query.casefold() in comment.content.casefold()
            ]
            items.append(
                ResearchSearchResult(
                    id=item.id,
                    document_id=item.target_document_id,
                    project_id=item.audience_project_id,
                    document_title=(
                        item.target_document.title
                        if item.target_document is not None
                        else None
                    ),
                    quote_text=thread.quote_text,
                    position=(
                        TypeAdapter(ResearchPosition).validate_python(thread.position)
                        if thread.position is not None
                        else None
                    ),
                    role=thread.role,
                    created_at=item.created_at,
                    matching_comments=comments,
                )
            )
        return ResearchSearchResponse(items=items, total=total)
