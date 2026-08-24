"""SQL-only bounded projection for MCP annotation-thread summary pages."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.database.models import (
    AnnotationComment,
    AnnotationThread,
    AuthUser,
    Document,
    Project,
    ProjectCollaborator,
    ProjectPaper,
    ResearchItem,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.research.application.annotation_summaries import (
    ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
    ANNOTATION_SUMMARY_QUOTE_JSON_BYTES,
    bounded_annotation_display_name,
    bounded_annotation_quote,
)
from app.modules.research.application.contracts import (
    AnnotationThreadCapabilities,
    AnnotationThreadSummaryResponse,
    PersonalResearchAudience,
    ProjectResearchAudience,
    ResearchCreatorResponse,
)
from app.modules.research.application.items import (
    AnnotationThreadSummaryKeyset,
    AnnotationThreadSummaryPage,
)
from app.modules.research.application.positions import (
    ParsedTextPosition,
    PdfTextPosition,
    PdfTextRect,
    ResearchPosition,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import (
    AnnotationAudienceFilter,
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from sqlalchemy import (
    Float,
    and_,
    case,
    cast as sql_cast,
    exists,
    func,
    or_,
    select,
    tuple_,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement


# PostgreSQL JSONB numbers are finite, but their text representation may still
# exceed the range accepted by a double-precision cast. Annotation coordinates
# only need ordinary decimal precision, so reject unusually large mantissas and
# exponents before the cast. The CASE arm is the only place where conversion is
# allowed; strings such as NaN/Infinity and non-scalar JSON values become NULL.
_SAFE_JSON_FLOAT_PATTERN = (
    r"^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,16})?"
    r"(?:[eE][+-]?[0-9]{1,2})?$"
)
_SAFE_JSON_FLOAT_CHARACTERS = 48


def _safe_json_float(value: Any) -> ColumnElement[float | None]:
    text_value = value.astext
    safe_numeric = and_(
        func.jsonb_typeof(value) == "number",
        func.length(text_value) <= _SAFE_JSON_FLOAT_CHARACTERS,
        text_value.op("~")(_SAFE_JSON_FLOAT_PATTERN),
    )
    return cast(
        ColumnElement[float | None],
        case(
            (safe_numeric, sql_cast(text_value, Float)),
            else_=None,
        ),
    )


class SqlAlchemyAnnotationSummaryCatalog:
    """Produce complete MCP list rows without loading an ORM Research item."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_page(
        self,
        *,
        document_id: UUID,
        user_id: int,
        project_id: UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
        after: AnnotationThreadSummaryKeyset | None,
        limit: int,
    ) -> AnnotationThreadSummaryPage:
        if limit < 1 or limit > 100:
            raise ValueError("annotation summary page limit must be between 1 and 100")
        can_edit_project = self._require_collection_access(
            document_id=document_id,
            user_id=user_id,
            project_id=project_id,
        )

        personal_filter = and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
        )
        project_filter = and_(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project_id,
        )
        audience_filter = (
            personal_filter
            if project_id is None
            else or_(personal_filter, project_filter)
        )
        if audience is AnnotationAudienceFilter.PERSONAL:
            audience_filter = personal_filter
        elif audience is AnnotationAudienceFilter.PROJECT:
            audience_filter = project_filter

        comment_count = (
            select(func.count(AnnotationComment.id))
            .where(AnnotationComment.thread_id == ResearchItem.id)
            .correlate(ResearchItem)
            .scalar_subquery()
        )
        last_comment_at = (
            select(func.max(AnnotationComment.updated_at))
            .where(AnnotationComment.thread_id == ResearchItem.id)
            .correlate(ResearchItem)
            .scalar_subquery()
        )
        foreign_reply_exists = exists(
            select(AnnotationComment.id)
            .where(
                AnnotationComment.thread_id == ResearchItem.id,
                AnnotationComment.created_by_id.is_distinct_from(user_id),
            )
            .correlate(ResearchItem)
        )
        position_kind_value = AnnotationThread.position["kind"]
        position_kind = case(
            (
                func.jsonb_typeof(position_kind_value) == "string",
                func.left(position_kind_value.astext, 32),
            ),
            else_=None,
        )
        pdf_anchor_y = _safe_json_float(AnnotationThread.position["rects"][0]["y"])
        pdf_anchor_x = _safe_json_float(AnnotationThread.position["rects"][0]["x"])
        pdf_width = _safe_json_float(AnnotationThread.position["rects"][0]["width"])
        pdf_height = _safe_json_float(AnnotationThread.position["rects"][0]["height"])
        page_number_null_rank = case(
            (AnnotationThread.page_number.is_(None), 1),
            else_=0,
        )
        anchor_y_null_rank = case((pdf_anchor_y.is_(None), 1), else_=0)
        anchor_x_null_rank = case((pdf_anchor_x.is_(None), 1), else_=0)
        start_offset_null_rank = case(
            (AnnotationThread.start_offset.is_(None), 1),
            else_=0,
        )
        end_offset_null_rank = case(
            (AnnotationThread.end_offset.is_(None), 1),
            else_=0,
        )
        sort_key = (
            page_number_null_rank,
            func.coalesce(AnnotationThread.page_number, 0),
            anchor_y_null_rank,
            func.coalesce(pdf_anchor_y, 0.0),
            anchor_x_null_rank,
            func.coalesce(pdf_anchor_x, 0.0),
            start_offset_null_rank,
            func.coalesce(AnnotationThread.start_offset, 0),
            end_offset_null_rank,
            func.coalesce(AnnotationThread.end_offset, 0),
            ResearchItem.created_at,
            ResearchItem.id,
        )
        creator = aliased(AuthUser, name="annotation_summary_creator")
        resolver = aliased(AuthUser, name="annotation_summary_resolver")
        creator_display_name = func.left(
            func.coalesce(
                func.nullif(func.btrim(creator.display_name), ""),
                creator.email,
            ),
            ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
        )
        resolver_display_name = func.left(
            func.coalesce(
                func.nullif(func.btrim(resolver.display_name), ""),
                resolver.email,
            ),
            ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
        )
        statement = (
            select(
                ResearchItem.id.label("item_id"),
                ResearchItem.audience_type,
                ResearchItem.audience_project_id,
                ResearchItem.target_document_id,
                ResearchItem.created_by_id,
                creator_display_name.label("creator_display_name"),
                ResearchItem.created_at,
                func.left(
                    AnnotationThread.quote_text,
                    ANNOTATION_SUMMARY_QUOTE_JSON_BYTES,
                ).label("quote_text"),
                position_kind.label("position_kind"),
                AnnotationThread.page_number,
                pdf_anchor_y.label("anchor_y"),
                pdf_anchor_x.label("anchor_x"),
                pdf_width.label("rect_width"),
                pdf_height.label("rect_height"),
                AnnotationThread.start_offset,
                AnnotationThread.end_offset,
                AnnotationThread.color,
                AnnotationThread.role,
                AnnotationThread.status,
                AnnotationThread.resolved_by_id,
                resolver_display_name.label("resolver_display_name"),
                AnnotationThread.resolved_at,
                comment_count.label("comment_count"),
                func.coalesce(last_comment_at, ResearchItem.created_at).label(
                    "last_activity_at"
                ),
                foreign_reply_exists.label("has_foreign_replies"),
            )
            .select_from(ResearchItem)
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .outerjoin(creator, creator.id == ResearchItem.created_by_id)
            .outerjoin(resolver, resolver.id == AnnotationThread.resolved_by_id)
            .where(
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                ResearchItem.target_document_id == document_id,
                audience_filter,
                AnnotationThread.status == status.value,
            )
            .order_by(
                AnnotationThread.page_number.asc().nulls_last(),
                pdf_anchor_y.asc().nulls_last(),
                pdf_anchor_x.asc().nulls_last(),
                AnnotationThread.start_offset.asc().nulls_last(),
                AnnotationThread.end_offset.asc().nulls_last(),
                ResearchItem.created_at.asc(),
                ResearchItem.id.asc(),
            )
        )
        if mode is AnnotationThreadMode.HIGHLIGHT:
            statement = statement.where(comment_count == 0)
        elif mode is AnnotationThreadMode.NOTE:
            statement = statement.where(
                ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
                comment_count > 0,
            )
        elif mode is AnnotationThreadMode.DISCUSSION:
            statement = statement.where(
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                comment_count > 0,
            )
        if after is not None:
            statement = statement.where(
                tuple_(*sort_key)
                > (
                    int(after.page_number is None),
                    after.page_number or 0,
                    int(after.anchor_y is None),
                    after.anchor_y or 0.0,
                    int(after.anchor_x is None),
                    after.anchor_x or 0.0,
                    int(after.start_offset is None),
                    after.start_offset or 0,
                    int(after.end_offset is None),
                    after.end_offset or 0,
                    after.created_at,
                    after.item_id,
                )
            )
        rows = list(self._db.execute(statement.limit(limit + 1)).mappings().all())
        page_rows = rows[:limit]
        items = [
            self._summary(
                row,
                user_id=user_id,
                can_edit_project=can_edit_project,
            )
            for row in page_rows
        ]
        return AnnotationThreadSummaryPage(
            items=items,
            next_keyset=(
                self._keyset(page_rows[-1]) if len(rows) > limit and page_rows else None
            ),
        )

    def _require_collection_access(
        self,
        *,
        document_id: UUID,
        user_id: int,
        project_id: UUID | None,
    ) -> bool:
        if (
            self._db.scalar(
                select(Document.id).where(
                    Document.id == document_id,
                    accessible_document_condition(user_id=user_id),
                )
            )
            is None
        ):
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        if project_id is None:
            return False
        project_access_level = cast(
            int | None,
            self._db.scalar(
                select(
                    case(
                        (Project.owner_id == user_id, 2),
                        (ProjectCollaborator.can_edit_project.is_(True), 1),
                        (ProjectCollaborator.user_id == user_id, 0),
                        else_=-1,
                    )
                )
                .select_from(Project)
                .outerjoin(
                    ProjectCollaborator,
                    and_(
                        ProjectCollaborator.project_id == Project.id,
                        ProjectCollaborator.user_id == user_id,
                    ),
                )
                .where(Project.id == project_id)
            ),
        )
        if project_access_level is None or project_access_level < 0:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        if (
            self._db.scalar(
                select(ProjectPaper.id).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.document_id == document_id,
                )
            )
            is None
        ):
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        return project_access_level > 0

    @staticmethod
    def _summary(
        row: Mapping[str, object] | RowMapping,
        *,
        user_id: int,
        can_edit_project: bool,
    ) -> AnnotationThreadSummaryResponse:
        item_id = cast(UUID, row["item_id"])
        target_document_id = cast(UUID | None, row["target_document_id"])
        if target_document_id is None:
            raise RuntimeError("annotation_summary_without_target_document")
        audience_type = ResearchAudienceType(cast(str, row["audience_type"]))
        is_project = audience_type is ResearchAudienceType.PROJECT
        audience_value: PersonalResearchAudience | ProjectResearchAudience
        if is_project:
            project_id = cast(UUID | None, row["audience_project_id"])
            if project_id is None:
                raise RuntimeError("project_annotation_without_project")
            audience_value = ProjectResearchAudience(project_id=project_id)
        else:
            audience_value = PersonalResearchAudience()
        comment_count = int(cast(int, row["comment_count"]))
        thread_status = AnnotationThreadStatus(cast(str, row["status"]))
        creator_id = cast(int | None, row["created_by_id"])
        is_creator = creator_id == user_id
        can_resolve = is_project and (is_creator or can_edit_project)
        resolved_by_id = cast(int | None, row["resolved_by_id"])
        return AnnotationThreadSummaryResponse(
            id=item_id,
            audience=audience_value,
            target_document_id=target_document_id,
            created_by=ResearchCreatorResponse(
                id=creator_id,
                display_name=bounded_annotation_display_name(
                    cast(str | None, row["creator_display_name"])
                ),
            ),
            created_at=cast(datetime, row["created_at"]),
            quote_text=bounded_annotation_quote(cast(str, row["quote_text"])),
            position=SqlAlchemyAnnotationSummaryCatalog._position(row),
            color=AnnotationColor(cast(str, row["color"])),
            role=cast(str, row["role"]),
            mode=(
                AnnotationThreadMode.HIGHLIGHT
                if comment_count == 0
                else (
                    AnnotationThreadMode.DISCUSSION
                    if is_project
                    else AnnotationThreadMode.NOTE
                )
            ),
            comment_count=comment_count,
            last_activity_at=cast(datetime, row["last_activity_at"]),
            status=thread_status,
            resolved_by=(
                ResearchCreatorResponse(
                    id=resolved_by_id,
                    display_name=bounded_annotation_display_name(
                        cast(str | None, row["resolver_display_name"])
                    ),
                )
                if resolved_by_id is not None
                else None
            ),
            resolved_at=cast(datetime | None, row["resolved_at"]),
            capabilities=AnnotationThreadCapabilities(
                reply=thread_status is AnnotationThreadStatus.OPEN,
                recolor=is_creator,
                resolve=(
                    can_resolve
                    and comment_count > 0
                    and thread_status is AnnotationThreadStatus.OPEN
                ),
                reopen=(
                    can_resolve and thread_status is AnnotationThreadStatus.RESOLVED
                ),
                delete=is_creator and not bool(row["has_foreign_replies"]),
            ),
            comments=[],
        )

    @staticmethod
    def _position(
        row: Mapping[str, object] | RowMapping,
    ) -> ResearchPosition | None:
        kind = cast(str | None, row["position_kind"])
        if kind is None:
            return None
        page_number = cast(int | None, row["page_number"])
        try:
            if kind == "pdf_text":
                if page_number is None:
                    return None
                return PdfTextPosition(
                    page_number=page_number,
                    rects=[
                        PdfTextRect(
                            x=float(cast(float, row["anchor_x"])),
                            y=float(cast(float, row["anchor_y"])),
                            width=float(cast(float, row["rect_width"])),
                            height=float(cast(float, row["rect_height"])),
                        )
                    ],
                    segments=None,
                )
            if kind == "parsed_text":
                start_offset = cast(int | None, row["start_offset"])
                end_offset = cast(int | None, row["end_offset"])
                if start_offset is None or end_offset is None:
                    return None
                return ParsedTextPosition(
                    start_offset=start_offset,
                    end_offset=end_offset,
                    page_number=page_number,
                )
        except (TypeError, ValueError, OverflowError):
            return None
        return None

    @staticmethod
    def _keyset(
        row: Mapping[str, object] | RowMapping,
    ) -> AnnotationThreadSummaryKeyset:
        return AnnotationThreadSummaryKeyset(
            page_number=cast(int | None, row["page_number"]),
            anchor_y=cast(float | None, row["anchor_y"]),
            anchor_x=cast(float | None, row["anchor_x"]),
            start_offset=cast(int | None, row["start_offset"]),
            end_offset=cast(int | None, row["end_offset"]),
            created_at=cast(datetime, row["created_at"]),
            item_id=cast(UUID, row["item_id"]),
        )


__all__ = ["SqlAlchemyAnnotationSummaryCatalog"]
