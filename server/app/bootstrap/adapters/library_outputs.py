"""Cross-module Library projection for visible Research outputs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.bootstrap.adapters.research_access import research_item_visible_to
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import (
    CitationOutput,
    Document,
    AnnotationComment,
    AnnotationThread,
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
from app.modules.research.application.legacy_outputs import (
    LegacyResearchListItemSize,
    legacy_research_list_payload_json_utf8_upper_bound,
    require_legacy_research_list_payload_budget,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind, ResearchAudienceType
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
        project_id: UUID | None = None,
        maximum_payload_json_bytes: int | None = None,
    ) -> LibraryOutputPage:
        title = self._title_expression()
        source_title = case(
            (
                ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
                func.coalesce(Document.title, Document.original_filename),
            ),
            (
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                Project.title,
            ),
            else_="Personal Library",
        )
        response_source_title = case(
            (
                ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
                func.coalesce(Document.title, Document.original_filename, "Paper"),
            ),
            (
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                func.coalesce(Project.title, "Project"),
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
        if project_id is not None:
            filters.extend(
                (
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == project_id,
                )
            )
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
        if maximum_payload_json_bytes is not None:
            return self._list_legacy_bounded(
                user_id=user_id,
                title=self._response_title_expression(),
                source_title=response_source_title,
                sort=sort,
                limit=limit,
                direction=direction,
                filters=filters,
                key=key,
                order=order,
                id_order=id_order,
                total_count=total_count,
                maximum_payload_json_bytes=maximum_payload_json_bytes,
            )
        statement = (
            self._base_statement()
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit + 1)
            .options(
                joinedload(ResearchItem.created_by),
                joinedload(ResearchItem.audience_document),
                joinedload(ResearchItem.audience_project),
                joinedload(ResearchItem.citation),
                joinedload(ResearchItem.audio_overview),
                joinedload(ResearchItem.data_table),
                joinedload(ResearchItem.annotation_thread).selectinload(
                    AnnotationThread.comments
                ),
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

    def _list_legacy_bounded(
        self,
        *,
        user_id: int,
        title: ColumnElement[str],
        source_title: ColumnElement[str],
        sort: LibraryOutputSort,
        limit: int,
        direction: LibraryPageDirection,
        filters: Sequence[ColumnElement[bool]],
        key: Any,
        order: Any,
        id_order: Any,
        total_count: int,
        maximum_payload_json_bytes: int,
    ) -> LibraryOutputPage:
        """Lock and size a historical full-output page before hydration."""

        scalar_statement = (
            self._base_statement()
            .with_only_columns(
                ResearchItem.id.label("item_id"),
                ResearchItem.kind,
                ResearchItem.audience_type,
                ResearchItem.audience_document_id,
                ResearchItem.audience_project_id,
                title.label("title"),
                source_title.label("source_title"),
                key.label("sort_key"),
            )
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit + 1)
            .with_for_update(of=ResearchItem)
        )
        rows = list(self._db.execute(scalar_statement).mappings().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is LibraryPageDirection.BACKWARD:
            rows.reverse()

        accesses = [
            research_repository.authorize_page(
                self._db,
                item_id=row["item_id"],
                user_id=user_id,
                include_access_url=False,
            )
            for row in rows
        ]
        payload_upper_bound = legacy_research_list_payload_json_utf8_upper_bound(
            LegacyResearchListItemSize(
                item_json_utf8_upper_bound=(
                    access.legacy_payload_json_utf8_upper_bound
                    if access.legacy_payload_json_utf8_upper_bound is not None
                    else access.durable_json_utf8_upper_bound
                ),
                title=cast(str | None, row["title"]),
                source_title=cast(str | None, row["source_title"]),
                wrapped=True,
            )
            for access, row in zip(accesses, rows, strict=True)
        )
        require_legacy_research_list_payload_budget(
            payload_json_utf8_upper_bound=payload_upper_bound,
            maximum_payload_json_bytes=maximum_payload_json_bytes,
        )

        item_ids = tuple(row["item_id"] for row in rows)
        hydrated = list(
            self._db.scalars(
                select(ResearchItem)
                .where(ResearchItem.id.in_(item_ids))
                .options(
                    joinedload(ResearchItem.created_by),
                    joinedload(ResearchItem.citation),
                    joinedload(ResearchItem.audio_overview),
                    joinedload(ResearchItem.data_table),
                    joinedload(ResearchItem.annotation_thread).joinedload(
                        AnnotationThread.resolved_by
                    ),
                    joinedload(ResearchItem.annotation_thread)
                    .selectinload(AnnotationThread.comments)
                    .joinedload(AnnotationComment.created_by),
                )
            )
            .unique()
            .all()
        )
        items_by_id = {item.id: item for item in hydrated}
        if set(items_by_id) != set(item_ids):
            raise RuntimeError("legacy_research_output_snapshot_incomplete")

        items = [
            self._response_from_scalar(
                items_by_id[row["item_id"]],
                user_id=user_id,
                title=cast(str, row["title"]),
                source_title=cast(str, row["source_title"]),
                audience_type=ResearchAudienceType(row["audience_type"]),
                audience_document_id=cast(UUID | None, row["audience_document_id"]),
                audience_project_id=cast(UUID | None, row["audience_project_id"]),
            )
            for row in rows
        ]
        for expected in accesses:
            current = research_repository.authorize_page(
                self._db,
                item_id=expected.item_id,
                user_id=user_id,
                include_access_url=False,
            )
            if current.revision != expected.revision:
                raise AppError(
                    code="research_output_snapshot_changed",
                    message="A research output changed while the page was prepared",
                    kind=FailureKind.CONFLICT,
                )
        return LibraryOutputPage(
            items=items,
            positions=[
                LibraryPagePosition(
                    key=self._scalar_key(
                        row["sort_key"],
                        response_title=row["title"],
                        sort=sort,
                    ),
                    id=row["item_id"],
                )
                for row in rows
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
            .outerjoin(Document, Document.id == ResearchItem.audience_document_id)
            .outerjoin(Project, Project.id == ResearchItem.audience_project_id)
            .outerjoin(
                AnnotationThread, AnnotationThread.research_item_id == ResearchItem.id
            )
            .outerjoin(
                CitationOutput, CitationOutput.research_item_id == ResearchItem.id
            )
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
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                func.left(AnnotationThread.quote_text, 240),
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

    @staticmethod
    def _response_title_expression() -> ColumnElement[str]:
        citation_title = CitationOutput.snapshot["data"]["title"].astext
        return case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                func.left(AnnotationThread.quote_text, 240),
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                func.coalesce(func.nullif(citation_title, ""), "Citation"),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                func.coalesce(
                    func.nullif(ResearchAudioOverview.title, ""),
                    "Audio overview",
                ),
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                func.coalesce(func.nullif(ResearchDataTable.title, ""), "Data table"),
            ),
            else_="Research output",
        )

    def _response(self, item: ResearchItem, *, user_id: int) -> LibraryOutputResponse:
        title = self._title(item)
        audience_type = ResearchAudienceType(item.audience_type)
        if audience_type is ResearchAudienceType.DOCUMENT:
            source_title = (
                (
                    item.audience_document.title
                    or item.audience_document.original_filename
                )
                if item.audience_document is not None
                else "Paper"
            )
            audience_id = item.audience_document_id
        elif audience_type is ResearchAudienceType.PROJECT:
            source_title = (
                item.audience_project.title
                if item.audience_project is not None
                else "Project"
            )
            audience_id = item.audience_project_id
        else:
            source_title = "Personal Library"
            audience_id = None
        return LibraryOutputResponse(
            item=research_repository.serialize(self._db, item=item, user_id=user_id),
            title=title,
            source=LibraryOutputSourceResponse(
                audience_type=audience_type,
                audience_id=audience_id,
                title=source_title,
            ),
        )

    def _response_from_scalar(
        self,
        item: ResearchItem,
        *,
        user_id: int,
        title: str,
        source_title: str,
        audience_type: ResearchAudienceType,
        audience_document_id: UUID | None,
        audience_project_id: UUID | None,
    ) -> LibraryOutputResponse:
        audience_id = (
            audience_document_id
            if audience_type is ResearchAudienceType.DOCUMENT
            else (
                audience_project_id
                if audience_type is ResearchAudienceType.PROJECT
                else None
            )
        )
        return LibraryOutputResponse(
            item=research_repository.serialize(self._db, item=item, user_id=user_id),
            title=title,
            source=LibraryOutputSourceResponse(
                audience_type=audience_type,
                audience_id=audience_id,
                title=source_title,
            ),
        )

    @staticmethod
    def _scalar_key(
        value: object,
        *,
        response_title: object,
        sort: LibraryOutputSort,
    ) -> str:
        if sort in {LibraryOutputSort.UPDATED_ASC, LibraryOutputSort.UPDATED_DESC}:
            if not isinstance(value, datetime):
                raise RuntimeError("legacy_research_output_timestamp_key_invalid")
            return value.isoformat()
        if not isinstance(response_title, str):
            raise RuntimeError("legacy_research_output_title_key_invalid")
        return response_title.lower()

    @classmethod
    def _key(cls, item: ResearchItem, *, sort: LibraryOutputSort) -> str:
        if sort in {LibraryOutputSort.UPDATED_ASC, LibraryOutputSort.UPDATED_DESC}:
            return item.updated_at.isoformat()
        return cls._title(item).lower()

    @staticmethod
    def _title(item: ResearchItem) -> str:
        if item.kind == ResearchItemKind.ANNOTATION_THREAD.value:
            return (
                item.annotation_thread.quote_text if item.annotation_thread else ""
            )[:240]
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
