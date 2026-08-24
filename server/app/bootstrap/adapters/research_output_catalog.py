"""SQL-only bounded projection for the Research-output catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import builtins
from typing import Any, cast
from uuid import UUID

from app.database.models import (
    AnnotationComment,
    AnnotationThread,
    AuthUser,
    CitationOutput,
    Document,
    LibraryPaper,
    Project,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
)
from app.bootstrap.adapters.research_access import research_item_visible_to
from app.modules.papers.infrastructure.access import require_document_access
from app.modules.projects.infrastructure.access import require_project_access
from app.modules.research.application.catalog import (
    ResearchOutputCatalogScope,
    ResearchOutputCatalogScopeKind,
    ResearchOutputCatalogSort,
    ResearchOutputPageDirection,
    ResearchOutputPagePosition,
    ResearchOutputSummaryPage,
)
from app.modules.research.application.contracts import (
    DocumentResearchAudience,
    PersonalResearchAudience,
    ProjectResearchAudience,
    ResearchAudience,
    ResearchOutputCreatorSummary,
    ResearchOutputSourceSummary,
    ResearchOutputSummary,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from app.shared.application.text import json_bounded_prefix
from app.shared.infrastructure.sql_patterns import literal_contains_pattern
from sqlalchemy import (
    Select,
    Text,
    and_,
    case,
    cast as sql_cast,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session, aliased
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import ColumnElement

_TITLE_CHARACTERS = 240
_EXCERPT_CHARACTERS = 1_200
_CREATOR_CHARACTERS = 320
_TITLE_UTF8_BYTES = 384
_SOURCE_TITLE_UTF8_BYTES = 384
_CREATOR_UTF8_BYTES = 512
_EXCERPT_UTF8_BYTES = 900
_JSON_SCALAR_PATH = (
    '$.** ? (@.type() == "string" || @.type() == "number" || @.type() == "boolean")'
)
_TABLE_PROJECTION_MAX_COLUMNS = 32
_TABLE_PROJECTION_MAX_SCALARS = 64
_TABLE_PROJECTION_VALUE_CHARACTERS = 128
_CITATION_PROJECTION_MAX_SCALARS = _EXCERPT_CHARACTERS
_CITATION_PROJECTION_VALUE_CHARACTERS = _EXCERPT_CHARACTERS


class SqlAlchemyResearchOutputCatalog:
    """Select only bounded scalar summaries; never hydrate full Research items."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audience_document = aliased(Document, name="output_audience_document")
        self._audience_project = aliased(Project, name="output_audience_project")

    def get(self, *, user_id: int, item_id: UUID) -> ResearchOutputSummary:
        """Select one authorized bounded summary without hydrating its payload."""

        title = self._title_expression()
        excerpt = self._excerpt_expression()
        source_title = self._source_title_expression()
        row = (
            self._db.execute(
                self._joined_statement(
                    ResearchItem.id.label("item_id"),
                    ResearchItem.kind.label("kind"),
                    ResearchItem.audience_type.label("audience_type"),
                    ResearchItem.audience_document_id.label("audience_document_id"),
                    ResearchItem.audience_project_id.label("audience_project_id"),
                    func.coalesce(
                        ResearchItem.target_document_id,
                        ResearchItem.audience_document_id,
                    ).label("target_document_id"),
                    ResearchItem.created_by_id.label("creator_id"),
                    func.left(
                        func.coalesce(
                            func.nullif(func.btrim(AuthUser.display_name), ""),
                            AuthUser.email,
                        ),
                        _CREATOR_CHARACTERS,
                    ).label("creator_display_name"),
                    ResearchItem.created_at.label("created_at"),
                    ResearchItem.updated_at.label("updated_at"),
                    title.label("title"),
                    excerpt.label("excerpt"),
                    source_title.label("source_title"),
                ).where(
                    ResearchItem.id == item_id,
                    research_item_visible_to(user_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AppError(
                code="research_output_not_found",
                message="The requested research output was not found",
                kind=FailureKind.NOT_FOUND,
            )
        return self._summary(row)

    def list(
        self,
        *,
        user_id: int,
        scope: ResearchOutputCatalogScope,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        sort: ResearchOutputCatalogSort,
        limit: int,
        direction: ResearchOutputPageDirection,
        position: ResearchOutputPagePosition | None,
        include_total_count: bool = True,
    ) -> ResearchOutputSummaryPage:
        self._require_scope_access(user_id=user_id, scope=scope)
        title = self._title_expression()
        excerpt = self._excerpt_expression()
        source_title = self._source_title_expression()
        filters = self._scope_filters(user_id=user_id, scope=scope)
        if kinds:
            filters.append(ResearchItem.kind.in_([kind.value for kind in kinds]))
        if query is not None:
            filters.append(self._search_predicate(literal_contains_pattern(query)))

        total_count = (
            int(
                self._db.scalar(
                    self._joined_statement(func.count(ResearchItem.id)).where(*filters)
                )
                or 0
            )
            if include_total_count
            else None
        )
        natural_ascending = sort in {
            ResearchOutputCatalogSort.UPDATED_ASC,
            ResearchOutputCatalogSort.TITLE_ASC,
        }
        key: ColumnElement[Any]
        cursor_key: object | None
        if sort in {
            ResearchOutputCatalogSort.UPDATED_ASC,
            ResearchOutputCatalogSort.UPDATED_DESC,
        }:
            key = cast(ColumnElement[Any], ResearchItem.updated_at)
            cursor_key = (
                datetime.fromisoformat(position.key) if position is not None else None
            )
        else:
            key = cast(ColumnElement[Any], func.lower(title))
            cursor_key = position.key if position is not None else None

        effective_ascending = (
            natural_ascending
            if direction is ResearchOutputPageDirection.FORWARD
            else not natural_ascending
        )
        if position is not None and cursor_key is not None:
            key_comparison = (
                key > cursor_key if effective_ascending else key < cursor_key
            )
            id_comparison = (
                ResearchItem.id > position.item_id
                if effective_ascending
                else ResearchItem.id < position.item_id
            )
            filters.append(
                or_(
                    key_comparison,
                    and_(key == cursor_key, id_comparison),
                )
            )

        statement = (
            self._joined_statement(
                ResearchItem.id.label("item_id"),
                ResearchItem.kind.label("kind"),
                ResearchItem.audience_type.label("audience_type"),
                ResearchItem.audience_document_id.label("audience_document_id"),
                ResearchItem.audience_project_id.label("audience_project_id"),
                func.coalesce(
                    ResearchItem.target_document_id,
                    ResearchItem.audience_document_id,
                ).label("target_document_id"),
                ResearchItem.created_by_id.label("creator_id"),
                func.left(
                    func.coalesce(
                        func.nullif(func.btrim(AuthUser.display_name), ""),
                        AuthUser.email,
                    ),
                    _CREATOR_CHARACTERS,
                ).label("creator_display_name"),
                ResearchItem.created_at.label("created_at"),
                ResearchItem.updated_at.label("updated_at"),
                title.label("title"),
                excerpt.label("excerpt"),
                source_title.label("source_title"),
                key.label("sort_key"),
            )
            .where(*filters)
            .order_by(
                key.asc() if effective_ascending else key.desc(),
                ResearchItem.id.asc()
                if effective_ascending
                else ResearchItem.id.desc(),
            )
            .limit(limit + 1)
        )
        rows = list(self._db.execute(statement).mappings().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ResearchOutputPageDirection.BACKWARD:
            rows.reverse()
        return ResearchOutputSummaryPage(
            items=[self._summary(row) for row in rows],
            positions=[self._position(row, sort=sort) for row in rows],
            has_more=has_more,
            total_count=total_count,
        )

    def _require_scope_access(
        self,
        *,
        user_id: int,
        scope: ResearchOutputCatalogScope,
    ) -> None:
        if scope.kind is ResearchOutputCatalogScopeKind.PROJECT:
            if scope.project_id is None:
                raise RuntimeError("project catalog scope is missing project_id")
            require_project_access(
                self._db,
                project_id=scope.project_id,
                user_id=user_id,
            )
        elif scope.kind is ResearchOutputCatalogScopeKind.PAPER:
            if scope.document_id is None:
                raise RuntimeError("paper catalog scope is missing document_id")
            require_document_access(
                self._db,
                document_id=scope.document_id,
                user_id=user_id,
                project_id=scope.project_id,
            )

    @staticmethod
    def _scope_filters(
        *,
        user_id: int,
        scope: ResearchOutputCatalogScope,
    ) -> builtins.list[ColumnElement[bool]]:
        if scope.kind is ResearchOutputCatalogScopeKind.LIBRARY:
            return [research_item_visible_to(user_id)]
        if scope.kind is ResearchOutputCatalogScopeKind.PERSONAL_LIBRARY:
            target_in_library = exists(
                select(LibraryPaper.id).where(
                    LibraryPaper.document_id == ResearchItem.target_document_id,
                    LibraryPaper.user_id == user_id,
                )
            )
            document_in_library = exists(
                select(LibraryPaper.id).where(
                    LibraryPaper.document_id == ResearchItem.audience_document_id,
                    LibraryPaper.user_id == user_id,
                )
            )
            return [
                or_(
                    and_(
                        ResearchItem.audience_type
                        == ResearchAudienceType.PERSONAL.value,
                        ResearchItem.created_by_id == user_id,
                        or_(
                            ResearchItem.target_document_id.is_(None),
                            target_in_library,
                        ),
                    ),
                    and_(
                        ResearchItem.audience_type
                        == ResearchAudienceType.DOCUMENT.value,
                        document_in_library,
                    ),
                )
            ]
        if scope.kind is ResearchOutputCatalogScopeKind.PROJECT:
            if scope.project_id is None:
                raise RuntimeError("project catalog scope is missing project_id")
            return [
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                ResearchItem.audience_project_id == scope.project_id,
            ]
        if scope.document_id is None:
            raise RuntimeError("paper catalog scope is missing document_id")
        personal_annotations = and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
        )
        annotation_audience = (
            personal_annotations
            if scope.project_id is None
            else or_(
                personal_annotations,
                and_(
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == scope.project_id,
                ),
            )
        )
        return [
            or_(
                and_(
                    ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                    ResearchItem.target_document_id == scope.document_id,
                    annotation_audience,
                ),
                and_(
                    ResearchItem.kind != ResearchItemKind.ANNOTATION_THREAD.value,
                    ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
                    ResearchItem.audience_document_id == scope.document_id,
                ),
            )
        ]

    def _joined_statement(self, *columns: Any) -> Select[Any]:
        return (
            select(*columns)
            .select_from(ResearchItem)
            .outerjoin(AuthUser, AuthUser.id == ResearchItem.created_by_id)
            .outerjoin(
                self._audience_document,
                self._audience_document.id == ResearchItem.audience_document_id,
            )
            .outerjoin(
                self._audience_project,
                self._audience_project.id == ResearchItem.audience_project_id,
            )
            .outerjoin(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .outerjoin(
                CitationOutput,
                CitationOutput.research_item_id == ResearchItem.id,
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

    @staticmethod
    def _title_expression() -> ColumnElement[str]:
        citation_title = CitationOutput.snapshot["data"]["title"].astext
        raw_title = case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                AnnotationThread.quote_text,
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                citation_title,
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                ResearchAudioOverview.title,
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                ResearchDataTable.title,
            ),
            else_="Research output",
        )
        fallback = case(
            (ResearchItem.kind == ResearchItemKind.CITATION.value, "Citation"),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                "Audio overview",
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                "Data table",
            ),
            else_="Research output",
        )
        return cast(
            ColumnElement[str],
            func.left(
                func.coalesce(func.nullif(func.btrim(raw_title), ""), fallback),
                _TITLE_CHARACTERS,
            ),
        )

    @staticmethod
    def _excerpt_expression() -> ColumnElement[str]:
        raw_excerpt = case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                AnnotationThread.quote_text,
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                SqlAlchemyResearchOutputCatalog._citation_text_expression(),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                ResearchAudioOverview.transcript,
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                SqlAlchemyResearchOutputCatalog._table_text_expression(),
            ),
            else_="",
        )
        return cast(
            ColumnElement[str],
            func.left(func.coalesce(raw_excerpt, ""), _EXCERPT_CHARACTERS),
        )

    @staticmethod
    def _search_predicate(pattern: str) -> ColumnElement[bool]:
        def matches(value: ColumnElement[str]) -> ColumnElement[bool]:
            return cast(
                ColumnElement[bool],
                func.lower(func.coalesce(value, "")).like(pattern, escape="\\"),
            )

        matching_comment = exists(
            select(AnnotationComment.id).where(
                AnnotationComment.thread_id == ResearchItem.id,
                matches(cast(ColumnElement[str], AnnotationComment.content)),
            )
        )
        return or_(
            and_(
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                or_(
                    matches(cast(ColumnElement[str], AnnotationThread.quote_text)),
                    matching_comment,
                ),
            ),
            and_(
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                SqlAlchemyResearchOutputCatalog._citation_search_predicate(pattern),
            ),
            and_(
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                matches(
                    cast(
                        ColumnElement[str],
                        func.concat_ws(
                            " ",
                            ResearchAudioOverview.title,
                            ResearchAudioOverview.transcript,
                        ),
                    )
                ),
            ),
            and_(
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                SqlAlchemyResearchOutputCatalog._table_search_predicate(pattern),
            ),
        )

    @staticmethod
    def _citation_text_expression() -> ColumnElement[str]:
        data = CitationOutput.snapshot["data"]
        bounded_scalar_fields = tuple(
            func.left(value, _EXCERPT_CHARACTERS)
            for value in SqlAlchemyResearchOutputCatalog._citation_scalar_fields()
        )
        return cast(
            ColumnElement[str],
            func.concat_ws(
                " ",
                bounded_scalar_fields[0],
                SqlAlchemyResearchOutputCatalog._bounded_json_scalar_values(
                    data["authors"],
                    alias_name="citation_author_scalars",
                    correlate_to=CitationOutput,
                    max_scalars=_CITATION_PROJECTION_MAX_SCALARS,
                    max_value_characters=_CITATION_PROJECTION_VALUE_CHARACTERS,
                    max_output_characters=_EXCERPT_CHARACTERS,
                    render_json_array=True,
                ),
                *bounded_scalar_fields[1:],
            ),
        )

    @staticmethod
    def _citation_scalar_fields() -> tuple[ColumnElement[str], ...]:
        data = CitationOutput.snapshot["data"]
        return (
            cast(ColumnElement[str], data["title"].astext),
            cast(ColumnElement[str], data["publish_date"].astext),
            cast(ColumnElement[str], data["journal"].astext),
            cast(ColumnElement[str], data["publisher"].astext),
            cast(ColumnElement[str], data["doi"].astext),
            cast(
                ColumnElement[str],
                CitationOutput.snapshot["preferred_style"].astext,
            ),
            cast(
                ColumnElement[str],
                CitationOutput.snapshot["style_display"].astext,
            ),
        )

    @staticmethod
    def _citation_search_predicate(pattern: str) -> ColumnElement[bool]:
        def matches(value: ColumnElement[str]) -> ColumnElement[bool]:
            return cast(
                ColumnElement[bool],
                func.lower(func.coalesce(value, "")).like(pattern, escape="\\"),
            )

        author_values = (
            func.jsonb_path_query(
                CitationOutput.snapshot["data"]["authors"],
                _JSON_SCALAR_PATH,
            )
            .table_valued("value")
            .render_derived(name="search_citation_authors")
        )
        matching_author = exists(
            select(1)
            .select_from(author_values)
            .where(matches(sql_cast(author_values.c.value, Text)))
            .correlate(CitationOutput)
        )
        return or_(
            *(
                matches(value)
                for value in SqlAlchemyResearchOutputCatalog._citation_scalar_fields()
            ),
            matching_author,
        )

    @staticmethod
    def _table_text_expression() -> ColumnElement[str]:
        return cast(
            ColumnElement[str],
            func.concat_ws(
                " ",
                ResearchDataTable.title,
                SqlAlchemyResearchOutputCatalog._bounded_table_columns(),
                SqlAlchemyResearchOutputCatalog._bounded_json_scalar_values(
                    ResearchDataTable.rows,
                    alias_name="table_row_scalars",
                    correlate_to=ResearchDataTable,
                ),
                SqlAlchemyResearchOutputCatalog._bounded_json_scalar_values(
                    ResearchDataTable.citations,
                    alias_name="table_citation_scalars",
                    correlate_to=ResearchDataTable,
                ),
                SqlAlchemyResearchOutputCatalog._bounded_json_scalar_values(
                    ResearchDataTable.row_failures,
                    alias_name="table_failure_scalars",
                    correlate_to=ResearchDataTable,
                ),
            ),
        )

    @staticmethod
    def _bounded_table_columns() -> ColumnElement[str]:
        values = (
            func.unnest(ResearchDataTable.columns)
            .table_valued("value")
            .render_derived(name="table_column_values")
        )
        limited = (
            select(
                func.left(
                    sql_cast(values.c.value, Text),
                    _TABLE_PROJECTION_VALUE_CHARACTERS,
                ).label("value")
            )
            .select_from(values)
            .limit(_TABLE_PROJECTION_MAX_COLUMNS)
            .correlate(ResearchDataTable)
            .subquery("bounded_table_column_values")
        )
        return cast(
            ColumnElement[str],
            select(func.coalesce(func.string_agg(limited.c.value, " "), ""))
            .select_from(limited)
            .scalar_subquery(),
        )

    @staticmethod
    def _bounded_json_scalar_values(
        value: object,
        *,
        alias_name: str,
        correlate_to: type[Any],
        max_scalars: int = _TABLE_PROJECTION_MAX_SCALARS,
        max_value_characters: int = _TABLE_PROJECTION_VALUE_CHARACTERS,
        max_output_characters: int | None = None,
        render_json_array: bool = False,
    ) -> ColumnElement[str]:
        values = (
            func.jsonb_path_query(value, _JSON_SCALAR_PATH)
            .table_valued("value")
            .render_derived(name=alias_name)
        )
        limited = (
            select(
                func.left(
                    sql_cast(values.c.value, Text),
                    max_value_characters,
                ).label("value")
            )
            .select_from(values)
            .limit(max_scalars)
            .correlate(correlate_to)
            .subquery(f"bounded_{alias_name}")
        )
        aggregate: ColumnElement[str] = cast(
            ColumnElement[str],
            func.coalesce(
                func.string_agg(
                    limited.c.value,
                    ", " if render_json_array else " ",
                ),
                "",
            ),
        )
        if render_json_array:
            aggregate = cast(
                ColumnElement[str],
                func.concat("[", aggregate, "]"),
            )
        if max_output_characters is not None:
            aggregate = cast(
                ColumnElement[str],
                func.left(aggregate, max_output_characters),
            )
        return cast(
            ColumnElement[str],
            select(aggregate).select_from(limited).scalar_subquery(),
        )

    @staticmethod
    def _table_search_predicate(pattern: str) -> ColumnElement[bool]:
        def matches(value: ColumnElement[str]) -> ColumnElement[bool]:
            return cast(
                ColumnElement[bool],
                func.lower(func.coalesce(value, "")).like(pattern, escape="\\"),
            )

        column_values = (
            func.unnest(ResearchDataTable.columns)
            .table_valued("value")
            .render_derived(name="search_table_columns")
        )
        predicates: list[ColumnElement[bool]] = [
            matches(cast(ColumnElement[str], ResearchDataTable.title)),
            exists(
                select(1)
                .select_from(column_values)
                .where(matches(sql_cast(column_values.c.value, Text)))
            ),
        ]
        for value, alias_name in (
            (ResearchDataTable.rows, "search_table_rows"),
            (ResearchDataTable.citations, "search_table_citations"),
            (ResearchDataTable.row_failures, "search_table_failures"),
        ):
            scalar_values = (
                func.jsonb_path_query(value, _JSON_SCALAR_PATH)
                .table_valued("value")
                .render_derived(name=alias_name)
            )
            predicates.append(
                exists(
                    select(1)
                    .select_from(scalar_values)
                    .where(matches(sql_cast(scalar_values.c.value, Text)))
                )
            )
        return or_(*predicates)

    def _source_title_expression(self) -> ColumnElement[str]:
        raw_title = case(
            (
                ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
                func.coalesce(
                    self._audience_document.title,
                    self._audience_document.original_filename,
                    "Paper",
                ),
            ),
            (
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                func.coalesce(self._audience_project.title, "Project"),
            ),
            else_="Personal Library",
        )
        return cast(ColumnElement[str], func.left(raw_title, _TITLE_CHARACTERS))

    @staticmethod
    def _summary(row: Mapping[str, object] | RowMapping) -> ResearchOutputSummary:
        item_id = cast(UUID, row["item_id"])
        kind = ResearchItemKind(cast(str, row["kind"]))
        audience_type = ResearchAudienceType(cast(str, row["audience_type"]))
        audience_id: UUID | None
        audience: ResearchAudience
        if audience_type is ResearchAudienceType.DOCUMENT:
            audience_id = cast(UUID | None, row["audience_document_id"])
            if audience_id is None:
                raise RuntimeError("document output is missing its audience document")
            audience = DocumentResearchAudience(document_id=audience_id)
        elif audience_type is ResearchAudienceType.PROJECT:
            audience_id = cast(UUID | None, row["audience_project_id"])
            if audience_id is None:
                raise RuntimeError("project output is missing its audience project")
            audience = ProjectResearchAudience(project_id=audience_id)
        else:
            audience_id = None
            audience = PersonalResearchAudience()
        resource_kind = (
            "annotation-threads"
            if kind is ResearchItemKind.ANNOTATION_THREAD
            else "research-outputs"
        )
        return ResearchOutputSummary(
            item_id=item_id,
            kind=kind,
            audience=audience,
            target_document_id=cast(UUID | None, row["target_document_id"]),
            title=json_bounded_prefix(
                cast(str, row["title"]),
                max_bytes=_TITLE_UTF8_BYTES,
            ),
            excerpt=json_bounded_prefix(
                cast(str, row["excerpt"]),
                max_bytes=_EXCERPT_UTF8_BYTES,
            ),
            creator=ResearchOutputCreatorSummary(
                id=cast(int | None, row["creator_id"]),
                display_name=(
                    json_bounded_prefix(
                        cast(str, row["creator_display_name"]),
                        max_bytes=_CREATOR_UTF8_BYTES,
                    )
                    if row["creator_display_name"] is not None
                    else None
                ),
            ),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
            source=ResearchOutputSourceSummary(
                audience_type=audience_type,
                audience_id=audience_id,
                title=json_bounded_prefix(
                    cast(str, row["source_title"]),
                    max_bytes=_SOURCE_TITLE_UTF8_BYTES,
                ),
            ),
            resource_uri=f"scholens://{resource_kind}/{item_id}",
        )

    @staticmethod
    def _position(
        row: Mapping[str, object] | RowMapping,
        *,
        sort: ResearchOutputCatalogSort,
    ) -> ResearchOutputPagePosition:
        raw_key = row["sort_key"]
        key = (
            cast(datetime, raw_key).isoformat()
            if sort
            in {
                ResearchOutputCatalogSort.UPDATED_ASC,
                ResearchOutputCatalogSort.UPDATED_DESC,
            }
            else cast(str, raw_key)
        )
        return ResearchOutputPagePosition(
            key=key,
            item_id=cast(UUID, row["item_id"]),
        )


__all__ = ["SqlAlchemyResearchOutputCatalog"]
