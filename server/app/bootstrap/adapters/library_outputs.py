"""Cross-module Library projection for visible Research outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from app.bootstrap.adapters.research_access import research_item_visible_to
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import (
    CitationOutput,
    Document,
    HighlightThread,
    Project,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
)
from app.modules.papers.application.contracts.documents import (
    LibraryOutputResponse,
    LibraryOutputSort,
    LibraryOutputSourceResponse,
)
from app.modules.papers.application.library import (
    LibraryOutputPage,
    LibraryPageDirection,
    LibraryPagePosition,
)
from app.shared.domain.enums import ResearchItemKind, ResearchScopeType
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql import Select


class SqlAlchemyLibraryOutputsGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list(
        self,
        *,
        user_id: int,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        sort: LibraryOutputSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryOutputPage:
        title = self._title_expression()
        source_title = case(
            (
                ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
                func.coalesce(Document.title, Document.original_filename),
            ),
            (
                ResearchItem.scope_type == ResearchScopeType.PROJECT.value,
                Project.title,
            ),
            else_="Personal Library",
        )
        if sort in {LibraryOutputSort.UPDATED_ASC, LibraryOutputSort.UPDATED_DESC}:
            key: Any = ResearchItem.updated_at
            cursor_key: Any = (
                datetime.fromisoformat(position.key) if position is not None else None
            )
            natural_ascending = sort is LibraryOutputSort.UPDATED_ASC
        else:
            key = func.lower(title)
            cursor_key = position.key if position is not None else None
            natural_ascending = sort is LibraryOutputSort.TITLE_ASC

        filters = [research_item_visible_to(user_id)]
        if kinds:
            filters.append(ResearchItem.kind.in_([kind.value for kind in kinds]))
        if query is not None:
            pattern = f"%{query.lower()}%"
            filters.append(
                or_(
                    func.lower(title).like(pattern),
                    func.lower(source_title).like(pattern),
                )
            )
        total_count = int(
            self._db.scalar(self._base_count_statement().where(*filters)) or 0
        )
        effective_ascending = (
            natural_ascending
            if direction is LibraryPageDirection.FORWARD
            else not natural_ascending
        )
        if position is not None and cursor_key is not None:
            comparison = key > cursor_key if effective_ascending else key < cursor_key
            id_comparison = (
                ResearchItem.id > position.id
                if effective_ascending
                else ResearchItem.id < position.id
            )
            filters.append(or_(comparison, and_(key == cursor_key, id_comparison)))
        order = key.asc() if effective_ascending else key.desc()
        id_order = (
            ResearchItem.id.asc() if effective_ascending else ResearchItem.id.desc()
        )
        statement = (
            self._base_statement()
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit + 1)
            .options(
                joinedload(ResearchItem.created_by),
                joinedload(ResearchItem.document),
                joinedload(ResearchItem.project),
                joinedload(ResearchItem.citation),
                joinedload(ResearchItem.audio_overview),
                joinedload(ResearchItem.data_table),
                joinedload(ResearchItem.highlight_thread)
                .selectinload(HighlightThread.comments),
            )
        )
        items = list(self._db.scalars(statement).unique().all())
        has_more = len(items) > limit
        items = items[:limit]
        if direction is LibraryPageDirection.BACKWARD:
            items.reverse()
        return LibraryOutputPage(
            items=[self._response(item, user_id=user_id) for item in items],
            positions=[
                LibraryPagePosition(key=self._key(item, sort=sort), id=item.id)
                for item in items
            ],
            has_more=has_more,
            total_count=total_count,
        )

    def count(self, *, user_id: int) -> int:
        return int(
            self._db.scalar(
                select(func.count(ResearchItem.id)).where(
                    research_item_visible_to(user_id)
                )
            )
            or 0
        )

    @staticmethod
    def _base_statement() -> Select[tuple[ResearchItem]]:
        return (
            select(ResearchItem)
            .outerjoin(Document, Document.id == ResearchItem.document_id)
            .outerjoin(Project, Project.id == ResearchItem.project_id)
            .outerjoin(HighlightThread, HighlightThread.research_item_id == ResearchItem.id)
            .outerjoin(CitationOutput, CitationOutput.research_item_id == ResearchItem.id)
            .outerjoin(
                ResearchAudioOverview,
                ResearchAudioOverview.research_item_id == ResearchItem.id,
            )
            .outerjoin(
                ResearchDataTable,
                ResearchDataTable.research_item_id == ResearchItem.id,
            )
        )

    @classmethod
    def _base_count_statement(cls) -> Select[tuple[int]]:
        return cls._base_statement().with_only_columns(func.count(ResearchItem.id))

    @staticmethod
    def _title_expression() -> ColumnElement[str]:
        citation_title = CitationOutput.snapshot["data"]["title"].astext
        return case(
            (
                ResearchItem.kind == ResearchItemKind.HIGHLIGHT_THREAD.value,
                func.left(HighlightThread.quote_text, 240),
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                func.coalesce(citation_title, "Citation"),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                func.coalesce(ResearchAudioOverview.title, "Audio overview"),
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                func.coalesce(ResearchDataTable.title, "Data table"),
            ),
            else_="Research output",
        )

    def _response(self, item: ResearchItem, *, user_id: int) -> LibraryOutputResponse:
        title = self._title(item)
        scope_type = ResearchScopeType(item.scope_type)
        if scope_type is ResearchScopeType.DOCUMENT:
            source_title = (
                (item.document.title or item.document.original_filename)
                if item.document is not None
                else "Paper"
            )
            scope_id = item.document_id
        elif scope_type is ResearchScopeType.PROJECT:
            source_title = item.project.title if item.project is not None else "Project"
            scope_id = item.project_id
        else:
            source_title = "Personal Library"
            scope_id = None
        return LibraryOutputResponse(
            item=research_repository.serialize(self._db, item=item, user_id=user_id),
            title=title,
            source=LibraryOutputSourceResponse(
                scope_type=scope_type,
                scope_id=scope_id,
                title=source_title,
            ),
        )

    @classmethod
    def _key(cls, item: ResearchItem, *, sort: LibraryOutputSort) -> str:
        if sort in {LibraryOutputSort.UPDATED_ASC, LibraryOutputSort.UPDATED_DESC}:
            return item.updated_at.isoformat()
        return cls._title(item).lower()

    @staticmethod
    def _title(item: ResearchItem) -> str:
        if item.kind == ResearchItemKind.HIGHLIGHT_THREAD.value:
            return (item.highlight_thread.quote_text if item.highlight_thread else "")[:240]
        if item.kind == ResearchItemKind.CITATION.value:
            data_value = item.citation.snapshot.get("data") if item.citation else None
            data = (
                cast(dict[str, object], data_value)
                if isinstance(data_value, dict)
                else {}
            )
            return str(data.get("title") or "Citation")
        if item.kind == ResearchItemKind.AUDIO_OVERVIEW.value:
            return (
                item.audio_overview.title if item.audio_overview else None
            ) or "Audio overview"
        return (item.data_table.title if item.data_table else None) or "Data table"
