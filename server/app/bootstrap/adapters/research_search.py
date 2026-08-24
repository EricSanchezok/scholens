"""SQL-only bounded projection for annotation-thread search."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from app.bootstrap.adapters.research_access import research_item_visible_to
from app.modules.papers.infrastructure.models import Document, LibraryPaper
from app.modules.research.application.positions import ResearchPosition
from app.modules.research.application.search import (
    ResearchSearchComment,
    ResearchSearchQuery,
    ResearchSearchResponse,
    ResearchSearchResult,
    ResearchSearchScope,
    ResearchSearchScopeKind,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    AnnotationThread,
    ResearchItem,
)
from app.shared.application import Actor
from app.shared.application.text import json_bounded_prefix
from app.shared.domain.enums import ResearchAudienceType
from app.shared.infrastructure.sql_patterns import literal_contains_pattern
from pydantic import TypeAdapter
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD = 3
RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT = 200

_TITLE_CHARACTERS = 240
_QUOTE_CHARACTERS = 1_200
_COMMENT_CHARACTERS = 1_200
_TITLE_JSON_BYTES = 384
_QUOTE_JSON_BYTES = 900
_COMMENT_JSON_BYTES = 900
_POSITION_ADAPTER: TypeAdapter[ResearchPosition] = TypeAdapter(ResearchPosition)


class SqlResearchSearch:
    """Search annotations without hydrating Research ORM graphs or full comments."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        actor: Actor,
        request: ResearchSearchQuery,
    ) -> ResearchSearchResponse:
        pattern = literal_contains_pattern(request.query.casefold())
        matching_comment = exists(
            select(AnnotationComment.id).where(
                AnnotationComment.thread_id == AnnotationThread.research_item_id,
                func.lower(AnnotationComment.content).like(pattern, escape="\\"),
            )
        )
        filters = (
            research_item_visible_to(actor.id),
            ResearchItem.target_document_id.is_not(None),
            or_(
                func.lower(AnnotationThread.quote_text).like(pattern, escape="\\"),
                matching_comment,
            ),
            *self._scope_filters(actor_id=actor.id, scope=request.scope),
        )
        continuation_filters: tuple[ColumnElement[bool], ...] = ()
        if request.after is not None:
            continuation_filters = (
                or_(
                    ResearchItem.created_at < request.after.created_at,
                    and_(
                        ResearchItem.created_at == request.after.created_at,
                        ResearchItem.id > request.after.item_id,
                    ),
                ),
            )
        base = (
            select(ResearchItem.id)
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .where(*filters, *continuation_filters)
        )
        total = (
            int(self._db.scalar(select(func.count()).select_from(base.subquery())) or 0)
            if request.include_total
            else 0
        )
        statement = (
            select(
                ResearchItem.id.label("thread_id"),
                ResearchItem.target_document_id.label("document_id"),
                ResearchItem.audience_project_id.label("project_id"),
                func.left(Document.title, _TITLE_CHARACTERS).label("document_title"),
                func.left(AnnotationThread.quote_text, _QUOTE_CHARACTERS).label(
                    "quote_text"
                ),
                AnnotationThread.position.label("position"),
                AnnotationThread.role.label("role"),
                ResearchItem.created_at.label("created_at"),
            )
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .outerjoin(Document, Document.id == ResearchItem.target_document_id)
            .where(*filters, *continuation_filters)
            .order_by(ResearchItem.created_at.desc(), ResearchItem.id)
            .offset(request.offset)
            .limit(request.limit)
        )
        rows = list(self._db.execute(statement).mappings().all())
        comments = self._matching_comments(
            thread_ids=[cast(UUID, row["thread_id"]) for row in rows],
            pattern=pattern,
        )
        return ResearchSearchResponse(
            items=[self._result(row, comments=comments) for row in rows],
            total=total,
        )

    def _matching_comments(
        self,
        *,
        thread_ids: list[UUID],
        pattern: str,
    ) -> dict[UUID, list[ResearchSearchComment]]:
        if not thread_ids:
            return {}
        ranked = (
            select(
                AnnotationComment.id.label("comment_id"),
                AnnotationComment.thread_id.label("thread_id"),
                func.left(AnnotationComment.content, _COMMENT_CHARACTERS).label(
                    "content"
                ),
                AnnotationComment.role.label("role"),
                AnnotationComment.created_at.label("created_at"),
                func.row_number()
                .over(
                    partition_by=AnnotationComment.thread_id,
                    order_by=(
                        AnnotationComment.created_at.asc(),
                        AnnotationComment.id.asc(),
                    ),
                )
                .label("thread_rank"),
            )
            .where(
                AnnotationComment.thread_id.in_(thread_ids),
                func.lower(AnnotationComment.content).like(pattern, escape="\\"),
            )
            .subquery("ranked_matching_comments")
        )
        statement = (
            select(
                ranked.c.comment_id,
                ranked.c.thread_id,
                ranked.c.content,
                ranked.c.role,
                ranked.c.created_at,
                ranked.c.thread_rank,
            )
            .where(ranked.c.thread_rank <= RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD)
            .order_by(
                ranked.c.thread_rank.asc(),
                ranked.c.created_at.asc(),
                ranked.c.comment_id.asc(),
            )
            .limit(RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT)
        )
        grouped: defaultdict[UUID, list[ResearchSearchComment]] = defaultdict(list)
        accepted = 0
        for row in self._db.execute(statement).mappings().all():
            if accepted >= RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT:
                break
            thread_id = cast(UUID, row["thread_id"])
            if len(grouped[thread_id]) >= RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD:
                continue
            grouped[thread_id].append(
                ResearchSearchComment(
                    id=cast(UUID, row["comment_id"]),
                    content=json_bounded_prefix(
                        cast(str, row["content"]),
                        max_bytes=_COMMENT_JSON_BYTES,
                    ),
                    role=cast(str, row["role"]),
                    created_at=cast(datetime, row["created_at"]),
                )
            )
            accepted += 1
        return dict(grouped)

    @staticmethod
    def _scope_filters(
        *,
        actor_id: int,
        scope: ResearchSearchScope,
    ) -> list[ColumnElement[bool]]:
        if scope.kind is ResearchSearchScopeKind.ALL_ACCESSIBLE:
            return []
        if scope.kind is ResearchSearchScopeKind.PERSONAL_LIBRARY:
            target_in_library = exists(
                select(LibraryPaper.id).where(
                    LibraryPaper.document_id == ResearchItem.target_document_id,
                    LibraryPaper.user_id == actor_id,
                )
            )
            return [
                ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
                ResearchItem.created_by_id == actor_id,
                target_in_library,
            ]
        if scope.kind is ResearchSearchScopeKind.PROJECT:
            if scope.project_id is None:
                raise RuntimeError(
                    "project research-search scope is missing project_id"
                )
            return [
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                ResearchItem.audience_project_id == scope.project_id,
            ]
        if scope.document_id is None:
            raise RuntimeError("paper research-search scope is missing document_id")
        personal = and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == actor_id,
        )
        audience = (
            personal
            if scope.project_id is None
            else or_(
                personal,
                and_(
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == scope.project_id,
                ),
            )
        )
        return [
            ResearchItem.target_document_id == scope.document_id,
            audience,
        ]

    @staticmethod
    def _result(
        row: Mapping[str, object] | RowMapping,
        *,
        comments: Mapping[UUID, list[ResearchSearchComment]],
    ) -> ResearchSearchResult:
        thread_id = cast(UUID, row["thread_id"])
        title = cast(str | None, row["document_title"])
        raw_position = row["position"]
        return ResearchSearchResult(
            id=thread_id,
            document_id=cast(UUID, row["document_id"]),
            project_id=cast(UUID | None, row["project_id"]),
            document_title=(
                json_bounded_prefix(title, max_bytes=_TITLE_JSON_BYTES)
                if title is not None
                else None
            ),
            quote_text=json_bounded_prefix(
                cast(str, row["quote_text"]),
                max_bytes=_QUOTE_JSON_BYTES,
            ),
            position=(
                _POSITION_ADAPTER.validate_python(raw_position)
                if raw_position is not None
                else None
            ),
            role=cast(str, row["role"]),
            created_at=cast(datetime, row["created_at"]),
            matching_comments=list(comments.get(thread_id, ())),
        )


__all__ = [
    "RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT",
    "RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD",
    "SqlResearchSearch",
]
