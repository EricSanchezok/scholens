"""Explicit persistence and visibility queries for typed research items."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast as type_cast

from app.database.models import (
    AnnotationComment,
    AnnotationColor,
    AnnotationThread,
    AnnotationThreadStatus,
    AuthUser,
    CitationOutput,
    Conversation,
    ConversationScopeType,
    Document,
    ResearchAudioOverview,
    ResearchAudienceType,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    RoleType,
)
from app.shared.domain.enums import AnnotationAudienceFilter, AnnotationThreadMode
from app.shared.domain import AppError, FailureKind
from app.helpers.s3 import s3_service
from app.modules.papers.infrastructure.access import (
    require_document_access,
)
from app.bootstrap.adapters.research_access import (
    research_item_policy,
    research_item_visible_to,
)
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadCapabilities,
    AnnotationThreadSummaryResponse,
    AudioOverviewContent,
    CitationContent,
    CitationSnapshot,
    DataTableContent,
    AnnotationThreadContent,
    DocumentResearchAudience,
    PersonalResearchAudience,
    ProjectResearchAudience,
    ResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
)
from app.modules.research.application.items import (
    ResearchItemPageAccess,
)
from app.modules.research.application.lifecycle import (
    AnnotationThreadDeletionPlan,
    AnnotationThreadDeletionState,
)
from app.modules.research.application.legacy_outputs import (
    LEGACY_RESEARCH_AUDIO_URL_JSON_UTF8_BYTES,
    LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES,
    LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES,
    LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES,
    LegacyResearchListItemSize,
    legacy_research_list_payload_json_utf8_upper_bound,
    require_legacy_research_list_payload_budget,
)
from app.modules.research.application.positions import (
    ParsedTextPosition,
    ResearchPosition,
    position_columns,
)
from pydantic import TypeAdapter
from sqlalchemy import Float, Text, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

_CITATION_SNAPSHOTS = TypeAdapter(list[CitationSnapshot])


def _normalize_whitespace(text: str) -> str:
    """Normalize Unicode/soft hyphens and collapse whitespace for anchors."""
    return " ".join(unicodedata.normalize("NFKC", text).replace("\u00ad", "").split())


@dataclass(frozen=True, slots=True)
class AnnotationThreadCreate:
    quote_text: str
    position: ResearchPosition | None
    color: str
    audience_type: ResearchAudienceType
    audience_project_id: uuid.UUID | None
    content_role: RoleType
    initial_comment: str | None = None
    zotero_annotation_key: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchItemWrite[T]:
    value: T
    changed: bool


@dataclass(frozen=True, slots=True)
class _AnnotationSummaryRecord:
    item: ResearchItem
    comment_count: int
    last_activity_at: datetime
    has_foreign_replies: bool


class ResearchRepository:
    def lock_legacy_read(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
    ) -> ResearchItemPageAccess:
        """Lock one visible item before a deprecated complete-object preflight."""

        locked_id = db.scalar(
            select(ResearchItem.id)
            .where(
                ResearchItem.id == item_id,
                research_item_visible_to(user_id),
            )
            .with_for_update(of=ResearchItem)
        )
        if locked_id is None:
            raise AppError(
                code="research_item_not_found",
                message="Research item not found",
                kind=FailureKind.NOT_FOUND,
            )
        return self.authorize_page(
            db,
            item_id=item_id,
            user_id=user_id,
            include_access_url=False,
        )

    def authorize_page(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        include_access_url: bool = True,
    ) -> ResearchItemPageAccess:
        """Authorize a full read using bounded scalar revision and size facts."""

        creator_revision = (
            select(AuthUser.updated_at)
            .where(AuthUser.id == ResearchItem.created_by_id)
            .scalar_subquery()
        )
        creator_bytes = (
            select(
                self._octets(
                    func.coalesce(
                        func.nullif(func.btrim(AuthUser.display_name), ""),
                        AuthUser.email,
                        "",
                    )
                )
            )
            .where(AuthUser.id == ResearchItem.created_by_id)
            .scalar_subquery()
        )
        resolved_user = aliased(AuthUser, name="page_resolved_user")
        payload_digest = case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                func.md5(
                    func.concat_ws(
                        "|",
                        func.md5(AnnotationThread.quote_text),
                        func.md5(cast(AnnotationThread.position, Text)),
                        AnnotationThread.color,
                        AnnotationThread.role,
                        AnnotationThread.status,
                        cast(AnnotationThread.resolved_by_id, Text),
                        cast(AnnotationThread.resolved_at, Text),
                    )
                ),
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                func.md5(cast(CitationOutput.snapshot, Text)),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                func.md5(
                    func.concat_ws(
                        "|",
                        func.md5(func.coalesce(ResearchAudioOverview.title, "")),
                        func.md5(ResearchAudioOverview.transcript),
                        func.md5(cast(ResearchAudioOverview.citations, Text)),
                        ResearchAudioOverview.s3_object_key,
                        ResearchAudioOverview.voice_id,
                        ResearchAudioOverview.model_version,
                    )
                ),
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                func.md5(
                    func.concat_ws(
                        "|",
                        func.md5(func.coalesce(ResearchDataTable.title, "")),
                        func.md5(
                            cast(func.array_to_json(ResearchDataTable.columns), Text)
                        ),
                        func.md5(cast(ResearchDataTable.rows, Text)),
                        func.md5(cast(ResearchDataTable.citations, Text)),
                        func.md5(cast(ResearchDataTable.row_failures, Text)),
                    )
                ),
            ),
            else_=None,
        )
        payload_json_utf8_bytes = case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                self._octets(cast(AnnotationThread.position, Text)),
            ),
            (
                ResearchItem.kind == ResearchItemKind.CITATION.value,
                self._octets(cast(CitationOutput.snapshot, Text)),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                self._octets(cast(ResearchAudioOverview.citations, Text)),
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                self._octets(cast(func.array_to_json(ResearchDataTable.columns), Text))
                + self._octets(cast(ResearchDataTable.rows, Text))
                + self._octets(cast(ResearchDataTable.citations, Text))
                + self._octets(cast(ResearchDataTable.row_failures, Text)),
            ),
            else_=0,
        )
        payload_string_utf8_bytes = case(
            (
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                self._octets(AnnotationThread.quote_text),
            ),
            (
                ResearchItem.kind == ResearchItemKind.AUDIO_OVERVIEW.value,
                self._octets(ResearchAudioOverview.title)
                + self._octets(ResearchAudioOverview.transcript)
                + self._octets(ResearchAudioOverview.s3_object_key)
                + self._octets(ResearchAudioOverview.voice_id)
                + self._octets(ResearchAudioOverview.model_version),
            ),
            (
                ResearchItem.kind == ResearchItemKind.DATA_TABLE.value,
                self._octets(ResearchDataTable.title),
            ),
            else_=0,
        )
        row = db.execute(
            select(
                ResearchItem.id.label("item_id"),
                ResearchItem.kind,
                ResearchItem.updated_at.label("item_updated_at"),
                AnnotationThread.updated_at.label("annotation_updated_at"),
                CitationOutput.updated_at.label("citation_updated_at"),
                ResearchAudioOverview.updated_at.label("audio_updated_at"),
                ResearchDataTable.updated_at.label("table_updated_at"),
                payload_digest.label("payload_digest"),
                payload_json_utf8_bytes.label("payload_json_utf8_bytes"),
                payload_string_utf8_bytes.label("payload_string_utf8_bytes"),
                creator_revision.label("creator_updated_at"),
                creator_bytes.label("creator_utf8_bytes"),
                resolved_user.updated_at.label("resolved_user_updated_at"),
                self._octets(
                    func.coalesce(
                        func.nullif(func.btrim(resolved_user.display_name), ""),
                        resolved_user.email,
                        "",
                    )
                ).label("resolved_user_utf8_bytes"),
                ResearchAudioOverview.s3_object_key.label("audio_object_key"),
            )
            .select_from(ResearchItem)
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
            .outerjoin(
                resolved_user,
                resolved_user.id == AnnotationThread.resolved_by_id,
            )
            .where(
                ResearchItem.id == item_id,
                research_item_visible_to(user_id),
            )
        ).one_or_none()
        if row is None or row.payload_digest is None:
            raise AppError(
                code="research_item_not_found",
                message="Research item not found",
                kind=FailureKind.NOT_FOUND,
            )

        comment_count = 0
        comment_utf8_bytes = 0
        comment_digest = ""
        comment_updated_at: datetime | None = None
        if row.kind == ResearchItemKind.ANNOTATION_THREAD.value:
            comment_creator = aliased(AuthUser, name="page_comment_creator")
            comment_token = func.md5(
                func.concat_ws(
                    "|",
                    cast(AnnotationComment.id, Text),
                    cast(AnnotationComment.created_by_id, Text),
                    cast(AnnotationComment.created_at, Text),
                    cast(AnnotationComment.updated_at, Text),
                    func.md5(AnnotationComment.content),
                    cast(comment_creator.updated_at, Text),
                )
            )
            comment_row: Any = db.execute(
                select(
                    func.count(AnnotationComment.id).label("comment_count"),
                    func.coalesce(
                        func.sum(self._octets(AnnotationComment.content)),
                        0,
                    ).label("content_utf8_bytes"),
                    func.coalesce(
                        func.sum(
                            self._octets(
                                func.coalesce(
                                    func.nullif(
                                        func.btrim(comment_creator.display_name), ""
                                    ),
                                    comment_creator.email,
                                    "",
                                )
                            )
                        ),
                        0,
                    ).label("creator_utf8_bytes"),
                    func.max(AnnotationComment.updated_at).label("updated_at"),
                    func.md5(
                        func.coalesce(
                            func.string_agg(
                                comment_token,
                                literal("").op("ORDER BY")(AnnotationComment.id),
                            ),
                            "",
                        )
                    ).label("revision_digest"),
                )
                .select_from(AnnotationComment)
                .outerjoin(
                    comment_creator,
                    comment_creator.id == AnnotationComment.created_by_id,
                )
                .where(AnnotationComment.thread_id == item_id)
            ).one()
            comment_count = int(comment_row.comment_count)
            comment_utf8_bytes = int(comment_row.content_utf8_bytes) + int(
                comment_row.creator_utf8_bytes
            )
            comment_digest = str(comment_row.revision_digest)
            comment_updated_at = comment_row.updated_at

        revision = hashlib.sha256(
            "|".join(
                str(value) if value is not None else ""
                for value in (
                    row.item_updated_at,
                    row.annotation_updated_at,
                    row.citation_updated_at,
                    row.audio_updated_at,
                    row.table_updated_at,
                    row.payload_digest,
                    row.creator_updated_at,
                    row.resolved_user_updated_at,
                    comment_count,
                    comment_updated_at,
                    comment_digest,
                )
            ).encode("utf-8")
        ).hexdigest()
        raw_string_utf8_bytes = (
            int(row.payload_string_utf8_bytes)
            + int(row.creator_utf8_bytes)
            + int(row.resolved_user_utf8_bytes)
            + comment_utf8_bytes
        )
        serialized_json_utf8_bytes = int(row.payload_json_utf8_bytes)
        retained_utf8_bytes = serialized_json_utf8_bytes + raw_string_utf8_bytes
        return ResearchItemPageAccess(
            item_id=row.item_id,
            kind=ResearchItemKind(row.kind),
            revision=revision,
            durable_json_utf8_upper_bound=(
                6 * retained_utf8_bytes + 2_048 * comment_count + 65_536
            ),
            legacy_payload_json_utf8_upper_bound=(
                serialized_json_utf8_bytes
                + 6 * raw_string_utf8_bytes
                + LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES * comment_count
                + LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES
                + (
                    LEGACY_RESEARCH_AUDIO_URL_JSON_UTF8_BYTES
                    if row.kind == ResearchItemKind.AUDIO_OVERVIEW.value
                    else 0
                )
            ),
            access_url=(
                s3_service.generate_presigned_url(row.audio_object_key)
                if include_access_url and row.audio_object_key is not None
                else None
            ),
        )

    @staticmethod
    def _octets(value: object) -> ColumnElement[int]:
        return type_cast(
            ColumnElement[int],
            func.coalesce(func.octet_length(value), 0),
        )

    def require_visible(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> ResearchItem:
        statement = select(ResearchItem).where(
            ResearchItem.id == item_id,
            research_item_visible_to(user_id),
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        item = db.scalar(statement)
        if item is None:
            raise AppError(
                code="research_item_not_found",
                message="Research item not found",
                kind=FailureKind.NOT_FOUND,
            )
        research_item_policy.require_visible(db, item=item, user_id=user_id)
        return item

    def get_annotation_thread(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
    ) -> ResearchItem:
        item = self.require_visible(db, item_id=thread_id, user_id=user_id)
        if (
            item.kind != ResearchItemKind.ANNOTATION_THREAD.value
            or item.annotation_thread is None
        ):
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        return item

    def plan_annotation_thread_delete(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
    ) -> AnnotationThreadDeletionPlan:
        item = self.require_creator_owned(
            db,
            item_id=thread_id,
            user_id=user_id,
            for_update=True,
        )
        if item.kind != ResearchItemKind.ANNOTATION_THREAD.value:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        thread_updated_at = db.scalar(
            select(AnnotationThread.updated_at)
            .where(AnnotationThread.research_item_id == thread_id)
            .with_for_update()
        )
        if thread_updated_at is None:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )

        revision = hashlib.sha256()
        comment_count = 0
        foreign_reply_count = 0
        for comment_id, creator_id, updated_at in db.execute(
            select(
                AnnotationComment.id,
                AnnotationComment.created_by_id,
                AnnotationComment.updated_at,
            )
            .where(AnnotationComment.thread_id == thread_id)
            .order_by(AnnotationComment.id)
            .with_for_update()
            .execution_options(yield_per=100)
        ):
            comment_count += 1
            if creator_id != user_id:
                foreign_reply_count += 1
            for field in (comment_id, creator_id, updated_at):
                encoded = ("" if field is None else str(field)).encode("utf-8")
                revision.update(len(encoded).to_bytes(8, "big"))
                revision.update(encoded)

        if foreign_reply_count:
            raise AppError(
                code="annotation_thread_has_other_replies",
                message="Resolve this thread to preserve other contributors' replies",
                kind=FailureKind.CONFLICT,
                details={"affected_reply_count": foreign_reply_count},
            )
        return AnnotationThreadDeletionPlan(
            state=AnnotationThreadDeletionState(
                thread_id=thread_id,
                creator_id=user_id,
                item_updated_at=item.updated_at,
                thread_updated_at=thread_updated_at,
                comment_count=comment_count,
                comment_revision_digest=revision.hexdigest(),
            )
        )

    def require_creator_owned(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> ResearchItem:
        item = self.require_visible(
            db,
            item_id=item_id,
            user_id=user_id,
            for_update=for_update,
        )
        research_item_policy.require_creator_manager(
            db,
            item=item,
            user_id=user_id,
        )
        return item

    def list_for_document(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        project_id: uuid.UUID | None = None,
        kind: ResearchItemKind | None = None,
    ) -> list[ResearchItem]:
        require_document_access(db, document_id=document_id, user_id=user_id)
        if project_id is not None:
            from app.modules.projects.infrastructure.access import (
                require_project_access,
            )
            from app.modules.projects.infrastructure.models import ProjectPaper

            require_project_access(db, project_id=project_id, user_id=user_id)
            if (
                db.scalar(
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
        personal_filter = and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
        )
        audience_filter = (
            personal_filter
            if project_id is None
            else or_(
                personal_filter,
                and_(
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == project_id,
                ),
            )
        )
        annotation_filter = and_(
            ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
            ResearchItem.target_document_id == document_id,
            audience_filter,
        )
        document_output_filter = and_(
            ResearchItem.kind != ResearchItemKind.ANNOTATION_THREAD.value,
            ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
            ResearchItem.audience_document_id == document_id,
        )
        statement = (
            select(ResearchItem)
            .where(or_(annotation_filter, document_output_filter))
            .order_by(ResearchItem.created_at.asc(), ResearchItem.id.asc())
            .options(
                joinedload(ResearchItem.created_by),
                joinedload(ResearchItem.citation),
                joinedload(ResearchItem.audio_overview),
                joinedload(ResearchItem.data_table),
                joinedload(ResearchItem.annotation_thread)
                .selectinload(AnnotationThread.comments)
                .joinedload(AnnotationComment.created_by),
            )
        )
        if kind is not None:
            statement = statement.where(ResearchItem.kind == kind.value)
        return list(db.scalars(statement).unique().all())

    def list_document_legacy(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        project_id: uuid.UUID | None,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        limit: int,
        maximum_payload_json_bytes: int,
    ) -> tuple[list[ResearchItemResponse], int]:
        """Preserve the historical paper branch without preflight bypasses.

        The old branch searched the complete serialized item, so a query must
        inspect every candidate. We first lock and size only scalar candidates;
        complete relationships are loaded only when that entire legacy search
        can fit the published result budget.
        """

        if not 1 <= limit <= 100:
            raise ValueError("legacy Research-output limit must be between 1 and 100")
        self._require_annotation_collection_access(
            db,
            document_id=document_id,
            user_id=user_id,
            project_id=project_id,
        )
        personal_filter = and_(
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
        )
        audience_filter = (
            personal_filter
            if project_id is None
            else or_(
                personal_filter,
                and_(
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == project_id,
                ),
            )
        )
        scope_filter = or_(
            and_(
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                ResearchItem.target_document_id == document_id,
                audience_filter,
            ),
            and_(
                ResearchItem.kind != ResearchItemKind.ANNOTATION_THREAD.value,
                ResearchItem.audience_type == ResearchAudienceType.DOCUMENT.value,
                ResearchItem.audience_document_id == document_id,
            ),
        )
        filters = [scope_filter]
        if kinds:
            filters.append(ResearchItem.kind.in_([kind.value for kind in kinds]))

        total_count = int(
            db.scalar(select(func.count(ResearchItem.id)).where(*filters)) or 0
        )
        if query is not None:
            minimum_payload_upper_bound = (
                LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES
                + total_count
                * LegacyResearchListItemSize(
                    item_json_utf8_upper_bound=(
                        LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES
                    )
                ).payload_json_utf8_upper_bound()
            )
            require_legacy_research_list_payload_budget(
                payload_json_utf8_upper_bound=minimum_payload_upper_bound,
                maximum_payload_json_bytes=maximum_payload_json_bytes,
            )
        id_statement = (
            select(ResearchItem.id)
            .where(*filters)
            .order_by(ResearchItem.created_at.asc(), ResearchItem.id.asc())
            .with_for_update(of=ResearchItem)
        )
        if query is None:
            id_statement = id_statement.limit(limit)
        item_ids = tuple(db.scalars(id_statement).all())
        accesses = [
            self.authorize_page(
                db,
                item_id=item_id,
                user_id=user_id,
                include_access_url=False,
            )
            for item_id in item_ids
        ]
        payload_upper_bound = legacy_research_list_payload_json_utf8_upper_bound(
            LegacyResearchListItemSize(
                item_json_utf8_upper_bound=(
                    access.legacy_payload_json_utf8_upper_bound
                    if access.legacy_payload_json_utf8_upper_bound is not None
                    else access.durable_json_utf8_upper_bound
                )
            )
            for access in accesses
        )
        require_legacy_research_list_payload_budget(
            payload_json_utf8_upper_bound=payload_upper_bound,
            maximum_payload_json_bytes=maximum_payload_json_bytes,
        )

        hydrated = list(
            db.scalars(
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
        by_id = {item.id: item for item in hydrated}
        if set(by_id) != set(item_ids):
            raise RuntimeError("legacy_research_output_snapshot_incomplete")
        responses = [
            self.serialize(db, item=by_id[item_id], user_id=user_id)
            for item_id in item_ids
        ]
        for expected in accesses:
            current = self.authorize_page(
                db,
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
        if query is not None:
            folded_query = query.casefold()
            responses = [
                item
                for item in responses
                if folded_query
                in json.dumps(
                    item.model_dump(mode="json"),
                    ensure_ascii=False,
                ).casefold()
            ]
            total_count = len(responses)
            responses = responses[:limit]
        return responses, total_count

    @staticmethod
    def _require_annotation_collection_access(
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        project_id: uuid.UUID | None,
    ) -> None:
        require_document_access(db, document_id=document_id, user_id=user_id)
        if project_id is None:
            return

        from app.modules.projects.infrastructure.access import require_project_access
        from app.modules.projects.infrastructure.models import ProjectPaper

        require_project_access(db, project_id=project_id, user_id=user_id)
        if (
            db.scalar(
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

    def _list_annotation_summary_records(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        project_id: uuid.UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
    ) -> list[_AnnotationSummaryRecord]:
        self._require_annotation_collection_access(
            db,
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
        foreign_reply_count = (
            select(func.count(AnnotationComment.id))
            .where(
                AnnotationComment.thread_id == ResearchItem.id,
                AnnotationComment.created_by_id.is_distinct_from(user_id),
            )
            .correlate(ResearchItem)
            .scalar_subquery()
        )
        pdf_anchor_y = cast(
            AnnotationThread.position["rects"][0]["y"].astext,
            Float,
        )
        pdf_anchor_x = cast(
            AnnotationThread.position["rects"][0]["x"].astext,
            Float,
        )
        statement = (
            select(
                ResearchItem,
                comment_count.label("comment_count"),
                func.coalesce(last_comment_at, ResearchItem.created_at).label(
                    "last_activity_at"
                ),
                foreign_reply_count.label("foreign_reply_count"),
            )
            .join(AnnotationThread)
            .where(
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                ResearchItem.target_document_id == document_id,
                audience_filter,
                AnnotationThread.status == status.value,
            )
            .options(
                joinedload(ResearchItem.created_by),
                joinedload(ResearchItem.annotation_thread).joinedload(
                    AnnotationThread.resolved_by
                ),
                joinedload(ResearchItem.annotation_thread)
                .selectinload(AnnotationThread.comments)
                .joinedload(AnnotationComment.created_by),
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
        return [
            _AnnotationSummaryRecord(
                item=item,
                comment_count=int(count),
                last_activity_at=last_activity_at_value,
                has_foreign_replies=int(foreign_count) > 0,
            )
            for item, count, last_activity_at_value, foreign_count in db.execute(
                statement
            ).unique()
        ]

    def _serialize_annotation_summary_records(
        self,
        db: Session,
        *,
        records: list[_AnnotationSummaryRecord],
        user_id: int,
    ) -> list[AnnotationThreadSummaryResponse]:
        return [
            self.serialize_annotation_summary(
                db,
                item=record.item,
                user_id=user_id,
                comment_count=record.comment_count,
                last_activity_at=record.last_activity_at,
                has_foreign_replies=record.has_foreign_replies,
            )
            for record in records
        ]

    def list_annotation_summaries(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        project_id: uuid.UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
    ) -> list[AnnotationThreadSummaryResponse]:
        records = self._list_annotation_summary_records(
            db,
            document_id=document_id,
            user_id=user_id,
            project_id=project_id,
            audience=audience,
            mode=mode,
            status=status,
        )
        return self._serialize_annotation_summary_records(
            db,
            records=records,
            user_id=user_id,
        )

    def list_for_project(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
    ) -> list[ResearchItem]:
        from app.modules.projects.infrastructure.access import require_project_access

        require_project_access(db, project_id=project_id, user_id=user_id)
        return list(
            db.scalars(
                select(ResearchItem)
                .where(
                    ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                    ResearchItem.audience_project_id == project_id,
                )
                .order_by(ResearchItem.created_at.desc(), ResearchItem.id.desc())
                .options(
                    joinedload(ResearchItem.created_by),
                    joinedload(ResearchItem.citation),
                    joinedload(ResearchItem.audio_overview),
                    joinedload(ResearchItem.data_table),
                )
            )
            .unique()
            .all()
        )

    def create_annotation_thread(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        create: AnnotationThreadCreate,
        refresh_result: bool = True,
    ) -> ResearchItem:
        require_document_access(
            db,
            document_id=document_id,
            user_id=user_id,
        )
        if create.audience_type not in {
            ResearchAudienceType.PERSONAL,
            ResearchAudienceType.PROJECT,
        }:
            raise ValueError("annotation audience must be personal or project")
        audience_project_id = (
            create.audience_project_id
            if create.audience_type is ResearchAudienceType.PROJECT
            else None
        )
        if create.audience_type is ResearchAudienceType.PROJECT:
            from app.modules.projects.infrastructure.access import (
                require_project_access_for_update,
            )

            if audience_project_id is None:
                raise ValueError("project annotation requires audience_project_id")
            require_project_access_for_update(
                db, project_id=audience_project_id, user_id=user_id
            )

        # Project-scoped creates lock Project then Document. Personal creates and
        # text-repair/removal workflows lock only Document, so all overlapping
        # mutation paths share a single acyclic lock order.
        locked_document = db.scalar(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_document is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_document_access(
            db,
            document_id=document_id,
            user_id=user_id,
            project_id=audience_project_id,
        )
        self._validate_quote_position(locked_document, create)
        if audience_project_id is not None:
            from app.modules.projects.infrastructure.models import ProjectPaper

            if (
                db.scalar(
                    select(ProjectPaper.id).where(
                        ProjectPaper.project_id == audience_project_id,
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
        page_number, start_offset, end_offset = position_columns(create.position)
        item = ResearchItem(
            kind=ResearchItemKind.ANNOTATION_THREAD.value,
            created_by_id=user_id,
            audience_type=create.audience_type.value,
            audience_project_id=create.audience_project_id,
            target_document_id=document_id,
        )
        item.annotation_thread = AnnotationThread(
            quote_text=create.quote_text,
            page_number=page_number,
            start_offset=start_offset,
            end_offset=end_offset,
            position=(
                create.position.model_dump(mode="json")
                if create.position is not None
                else None
            ),
            color=create.color,
            role=create.content_role.value,
            zotero_annotation_key=create.zotero_annotation_key,
        )
        db.add(item)
        db.flush()
        if create.initial_comment is not None:
            item.annotation_thread.comments.append(
                AnnotationComment(
                    created_by_id=user_id,
                    content=create.initial_comment,
                    role=create.content_role.value,
                )
            )
        if refresh_result:
            db.flush()
            db.refresh(item)
        else:
            db.flush()
        return item

    @staticmethod
    def _validate_quote_position(
        document: Document,
        create: AnnotationThreadCreate,
    ) -> None:
        """Reject parsed-text anchors whose window does not cover the quote.

        A ``parsed_text`` position must point at the exact quote in the
        canonical parsed content. Previously the anchor was persisted
        verbatim, so a 3-character window could be stored for a 200-character
        quote and every Reader highlight built from it was corrupted.
        Whitespace is normalized so selection/OCR whitespace differences do
        not create false rejections.
        """
        position = create.position
        if not isinstance(position, ParsedTextPosition):
            return
        quote = create.quote_text
        if not quote:
            return
        raw_content = document.raw_content
        if not raw_content:
            raise AppError(
                code="annotation_content_unavailable",
                message=(
                    "Parsed document content is unavailable; use a PDF text "
                    "anchor or retry after parsing completes"
                ),
                kind=FailureKind.CONFLICT,
            )
        window = raw_content[position.start_offset : position.end_offset]
        if _normalize_whitespace(window) != _normalize_whitespace(quote):
            raise AppError(
                code="annotation_quote_mismatch",
                message=(
                    "The anchor offsets do not match the quote text in the "
                    "document content"
                ),
                kind=FailureKind.INVALID_ARGUMENT,
            )

    def has_assistant_annotation(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> bool:
        return (
            db.scalar(
                select(ResearchItem.id)
                .join(
                    AnnotationThread,
                    AnnotationThread.research_item_id == ResearchItem.id,
                )
                .where(
                    ResearchItem.target_document_id == document_id,
                    ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
                    ResearchItem.created_by_id == user_id,
                    AnnotationThread.role == RoleType.ASSISTANT.value,
                )
                .limit(1)
            )
            is not None
        )

    def create_citation(
        self,
        db: Session,
        *,
        user_id: int,
        snapshot: CitationSnapshot,
        source_response_id: uuid.UUID,
        scope_type: ResearchAudienceType,
        scope_id: uuid.UUID | None,
    ) -> ResearchItem:
        item = ResearchItem(
            kind=ResearchItemKind.CITATION.value,
            created_by_id=user_id,
            audience_type=scope_type.value,
            audience_document_id=(
                scope_id if scope_type == ResearchAudienceType.DOCUMENT else None
            ),
            audience_project_id=(
                scope_id if scope_type == ResearchAudienceType.PROJECT else None
            ),
            source_response_id=source_response_id,
        )
        item.citation = CitationOutput(snapshot=snapshot.model_dump(mode="json"))
        db.add(item)
        return item

    def create_citations_for_response(
        self,
        db: Session,
        *,
        conversation: Conversation,
        response_id: uuid.UUID,
        user_id: int,
        snapshots: list[dict[str, object]],
    ) -> list[ResearchItem]:
        scope_type = ConversationScopeType(conversation.scope_type)
        if scope_type == ConversationScopeType.GLOBAL:
            research_scope = ResearchAudienceType.PERSONAL
            scope_id = None
        elif scope_type == ConversationScopeType.PROJECT:
            research_scope = ResearchAudienceType.PROJECT
            scope_id = conversation.project_id
        else:
            research_scope = ResearchAudienceType.DOCUMENT
            scope_id = conversation.document_id
        validated_snapshots = _CITATION_SNAPSHOTS.validate_python(snapshots)
        items = [
            self.create_citation(
                db,
                user_id=user_id,
                snapshot=snapshot,
                source_response_id=response_id,
                scope_type=research_scope,
                scope_id=scope_id,
            )
            for snapshot in validated_snapshots
        ]
        db.flush()
        return items

    def get_annotation_thread_visible(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
    ) -> ResearchItem:
        item = db.scalar(
            select(ResearchItem)
            .where(
                ResearchItem.id == thread_id,
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                research_item_visible_to(user_id),
            )
            .options(
                joinedload(ResearchItem.annotation_thread)
                .selectinload(AnnotationThread.comments)
                .joinedload(AnnotationComment.created_by),
                joinedload(ResearchItem.created_by),
            )
        )
        if item is None:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        research_item_policy.require_visible(db, item=item, user_id=user_id)
        return item

    def get_annotation_threads_visible(
        self,
        db: Session,
        *,
        thread_ids: Iterable[uuid.UUID],
        user_id: int,
    ) -> list[ResearchItem]:
        """Return visible annotation threads in first-seen input order.

        The query reuses the complete Research-item audience predicate used by
        the single-thread lookup. Missing, inaccessible, non-thread, and
        duplicate identifiers are omitted without issuing per-thread
        authorization or comment queries.
        """

        ordered_ids = list(dict.fromkeys(thread_ids))
        if not ordered_ids:
            return []
        items = (
            db.scalars(
                select(ResearchItem)
                .where(
                    ResearchItem.id.in_(ordered_ids),
                    ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                    research_item_visible_to(user_id),
                )
                .options(
                    joinedload(ResearchItem.annotation_thread).options(
                        selectinload(AnnotationThread.comments)
                    )
                )
            )
            .unique()
            .all()
        )
        items_by_id = {item.id: item for item in items}
        return [
            item
            for thread_id in ordered_ids
            if (item := items_by_id.get(thread_id)) is not None
        ]

    def get_zotero_annotation_keys(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> set[str]:
        return {
            key
            for key in db.scalars(
                select(AnnotationThread.zotero_annotation_key)
                .join(
                    ResearchItem,
                    ResearchItem.id == AnnotationThread.research_item_id,
                )
                .where(
                    ResearchItem.target_document_id == document_id,
                    ResearchItem.created_by_id == user_id,
                    AnnotationThread.zotero_annotation_key.isnot(None),
                )
            ).all()
            if key is not None
        }

    def find_zotero_backfill_candidate(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        quote_text: str,
        page_number: int | None,
    ) -> AnnotationThread | None:
        return db.scalar(
            select(AnnotationThread)
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationThread.research_item_id,
            )
            .where(
                ResearchItem.target_document_id == document_id,
                ResearchItem.created_by_id == user_id,
                AnnotationThread.zotero_annotation_key.is_(None),
                AnnotationThread.quote_text == quote_text,
                AnnotationThread.page_number.is_not_distinct_from(page_number),
            )
            .order_by(ResearchItem.created_at.asc())
            .limit(1)
        )

    @staticmethod
    def set_zotero_annotation_key(
        db: Session,
        *,
        thread: AnnotationThread,
        zotero_annotation_key: str,
    ) -> None:
        thread.zotero_annotation_key = zotero_annotation_key
        db.flush()

    def add_comment(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
        content: str,
        content_role: RoleType,
        refresh_result: bool = True,
    ) -> AnnotationComment:
        item = self.require_visible(
            db,
            item_id=thread_id,
            user_id=user_id,
            for_update=True,
        )
        if item.kind != ResearchItemKind.ANNOTATION_THREAD.value:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        access = research_item_policy.evaluate(db, item=item, user_id=user_id)
        if not access.has_audience_access:
            raise AppError(
                code="research_item_scope_access_lost",
                message="This thread is read-only until scope access is restored",
                kind=FailureKind.CONFLICT,
            )
        thread = db.scalar(
            select(AnnotationThread)
            .where(AnnotationThread.research_item_id == thread_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if thread is None:
            raise RuntimeError("annotation_item_without_thread")
        if thread.status == "resolved":
            raise AppError(
                code="annotation_thread_resolved",
                message="Reopen this thread before replying",
                kind=FailureKind.CONFLICT,
            )
        comment = AnnotationComment(
            thread_id=thread_id,
            created_by_id=user_id,
            content=content,
            role=content_role.value,
        )
        db.add(comment)
        if refresh_result:
            db.flush()
            db.refresh(comment)
        else:
            db.flush()
        return comment

    def require_owned_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> AnnotationComment:
        statement = (
            select(AnnotationComment)
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationComment.thread_id,
            )
            .where(
                AnnotationComment.id == comment_id,
                AnnotationComment.created_by_id == user_id,
                research_item_visible_to(user_id),
            )
        )
        if for_update:
            thread_id = db.scalar(
                select(AnnotationComment.thread_id)
                .join(
                    ResearchItem,
                    ResearchItem.id == AnnotationComment.thread_id,
                )
                .where(
                    AnnotationComment.id == comment_id,
                    AnnotationComment.created_by_id == user_id,
                    research_item_visible_to(user_id),
                )
            )
            if thread_id is None:
                raise AppError(
                    code="annotation_comment_not_found",
                    message="Annotation comment not found",
                    kind=FailureKind.NOT_FOUND,
                )
            self.require_visible(
                db,
                item_id=thread_id,
                user_id=user_id,
                for_update=True,
            )
            statement = (
                select(AnnotationComment)
                .where(
                    AnnotationComment.id == comment_id,
                    AnnotationComment.thread_id == thread_id,
                    AnnotationComment.created_by_id == user_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        comment = db.scalar(statement)
        if comment is None:
            raise AppError(
                code="annotation_comment_not_found",
                message="Annotation comment not found",
                kind=FailureKind.NOT_FOUND,
            )
        item = db.get(ResearchItem, comment.thread_id)
        if item is None:
            raise RuntimeError("annotation_comment_without_research_item")
        research_item_policy.require_visible(db, item=item, user_id=user_id)
        return comment

    def update_annotation_thread(
        self,
        db: Session,
        *,
        thread_id: uuid.UUID,
        user_id: int,
        values: dict[str, object],
    ) -> ResearchItemWrite[ResearchItem]:
        item = self.require_visible(
            db, item_id=thread_id, user_id=user_id, for_update=True
        )
        if (
            item.kind != ResearchItemKind.ANNOTATION_THREAD.value
            or item.annotation_thread is None
        ):
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        access = research_item_policy.evaluate(db, item=item, user_id=user_id)
        changed = False
        color = values.get("color")
        status = values.get("status")
        if color is not None:
            if not access.can_manage:
                raise AppError(
                    code="research_item_permission_denied",
                    message="Only the creator can recolor this annotation",
                    kind=FailureKind.PERMISSION_DENIED,
                )
            next_color = getattr(color, "value", color)
            if item.annotation_thread.color != next_color:
                item.annotation_thread.color = str(next_color)
                changed = True
        if status is not None:
            if item.audience_type != ResearchAudienceType.PROJECT.value:
                raise AppError(
                    code="personal_annotation_cannot_be_resolved",
                    message="Personal annotations are deleted instead of resolved",
                    kind=FailureKind.CONFLICT,
                )
            if not access.can_resolve:
                raise AppError(
                    code="annotation_thread_resolution_denied",
                    message="Project edit permission is required",
                    kind=FailureKind.PERMISSION_DENIED,
                )
            next_status = getattr(status, "value", status)
            if (
                next_status == "resolved"
                and db.scalar(
                    select(AnnotationComment.id)
                    .where(AnnotationComment.thread_id == thread_id)
                    .limit(1)
                )
                is None
            ):
                raise AppError(
                    code="annotation_thread_has_no_discussion",
                    message="A commentless mark is deleted instead of resolved",
                    kind=FailureKind.CONFLICT,
                )
            if item.annotation_thread.status != next_status:
                item.annotation_thread.status = str(next_status)
                if next_status == "resolved":
                    item.annotation_thread.resolved_by_id = user_id
                    item.annotation_thread.resolved_at = datetime.now(timezone.utc)
                else:
                    item.annotation_thread.resolved_by_id = None
                    item.annotation_thread.resolved_at = None
                changed = True
        if not changed:
            return ResearchItemWrite(value=item, changed=False)
        item.updated_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(item)
        return ResearchItemWrite(value=item, changed=True)

    def serialize_annotation_mutation_response(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemResponse:
        """Build an exact mutation receipt without loading comment bodies."""

        stats = db.execute(
            select(
                func.count(AnnotationComment.id).label("comment_count"),
                func.max(AnnotationComment.updated_at).label("last_activity_at"),
                func.count(AnnotationComment.id)
                .filter(AnnotationComment.created_by_id.is_distinct_from(user_id))
                .label("foreign_reply_count"),
            ).where(AnnotationComment.thread_id == item.id)
        ).one()
        summary = self.serialize_annotation_summary(
            db,
            item=item,
            user_id=user_id,
            comment_count=int(stats.comment_count),
            last_activity_at=stats.last_activity_at or item.created_at,
            has_foreign_replies=bool(stats.foreign_reply_count),
            include_comments=False,
        )
        return ResearchItemResponse(
            id=summary.id,
            kind=ResearchItemKind.ANNOTATION_THREAD,
            audience=summary.audience,
            target_document_id=summary.target_document_id,
            created_by=summary.created_by,
            created_at=summary.created_at,
            updated_at=item.updated_at,
            capabilities=ResearchItemCapabilities(
                edit=summary.capabilities.recolor,
                delete=summary.capabilities.delete,
            ),
            annotation_thread=AnnotationThreadContent(
                quote_text=summary.quote_text,
                position=summary.position,
                color=summary.color,
                role=summary.role,
                mode=summary.mode,
                comment_count=summary.comment_count,
                last_activity_at=summary.last_activity_at,
                status=summary.status,
                resolved_by=summary.resolved_by,
                resolved_at=summary.resolved_at,
                capabilities=summary.capabilities,
                comments=list(summary.comments),
            ),
        )

    def update_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
        content: str,
    ) -> ResearchItemWrite[AnnotationComment]:
        comment = self.require_owned_comment(
            db,
            comment_id=comment_id,
            user_id=user_id,
            for_update=True,
        )
        if comment.content == content:
            return ResearchItemWrite(value=comment, changed=False)
        comment.content = content
        db.flush()
        db.refresh(comment)
        return ResearchItemWrite(value=comment, changed=True)

    def delete_comment(
        self,
        db: Session,
        *,
        comment_id: uuid.UUID,
        user_id: int,
    ) -> None:
        comment = self.require_owned_comment(
            db,
            comment_id=comment_id,
            user_id=user_id,
            for_update=True,
        )
        db.delete(comment)
        db.flush()

    def delete_item(
        self,
        db: Session,
        *,
        item_id: uuid.UUID,
        user_id: int,
        origin_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> None:
        item = self.require_creator_owned(
            db,
            item_id=item_id,
            user_id=user_id,
            for_update=True,
        )
        if item.kind == ResearchItemKind.ANNOTATION_THREAD.value:
            other_reply_count = int(
                db.scalar(
                    select(func.count(AnnotationComment.id)).where(
                        AnnotationComment.thread_id == item.id,
                        AnnotationComment.created_by_id.is_distinct_from(user_id),
                    )
                )
                or 0
            )
            if other_reply_count:
                raise AppError(
                    code="annotation_thread_has_other_replies",
                    message="Resolve this thread to preserve other contributors' replies",
                    kind=FailureKind.CONFLICT,
                    details={"affected_reply_count": other_reply_count},
                )
        object_key = (
            item.audio_overview.s3_object_key
            if item.audio_overview is not None
            else None
        )
        db.delete(item)
        db.flush()
        if object_key is not None:
            from app.bootstrap.adapters.storage_cleanup import (
                schedule_storage_deletion,
            )

            schedule_storage_deletion(
                db,
                object_keys=[object_key],
                idempotency_key=f"research-item:{item.id}",
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
        db.flush()

    @staticmethod
    def _creator_response(
        user_id: int | None,
        user: AuthUser | None,
    ) -> ResearchCreatorResponse:
        if user is None:
            return ResearchCreatorResponse(id=user_id, display_name=None)
        display_name = (user.display_name or "").strip() or user.email
        return ResearchCreatorResponse(id=user_id, display_name=display_name)

    def serialize(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemResponse:
        access = research_item_policy.require_visible(
            db,
            item=item,
            user_id=user_id,
        )
        creator = self._creator_response(item.created_by_id, item.created_by)
        audience_type = ResearchAudienceType(item.audience_type)
        audience: ResearchAudience
        if audience_type is ResearchAudienceType.DOCUMENT:
            if item.audience_document_id is None:
                raise RuntimeError("document_audience_without_document")
            audience = DocumentResearchAudience(document_id=item.audience_document_id)
        elif audience_type is ResearchAudienceType.PROJECT:
            if item.audience_project_id is None:
                raise RuntimeError("project_audience_without_project")
            audience = ProjectResearchAudience(project_id=item.audience_project_id)
        else:
            audience = PersonalResearchAudience()
        annotation: AnnotationThreadContent | None = None
        citation: CitationContent | None = None
        audio: AudioOverviewContent | None = None
        data_table: DataTableContent | None = None
        if item.annotation_thread is not None:
            resolved_by = item.annotation_thread.resolved_by
            comment_count = len(item.annotation_thread.comments)
            annotation_mode = (
                AnnotationThreadMode.HIGHLIGHT
                if comment_count == 0
                else (
                    AnnotationThreadMode.DISCUSSION
                    if item.audience_type == ResearchAudienceType.PROJECT.value
                    else AnnotationThreadMode.NOTE
                )
            )
            last_activity_at = max(
                (comment.updated_at for comment in item.annotation_thread.comments),
                default=item.created_at,
            )
            has_foreign_replies = any(
                comment.created_by_id != user_id
                for comment in item.annotation_thread.comments
            )
            can_delete_annotation = access.can_manage and not has_foreign_replies
            annotation = AnnotationThreadContent(
                quote_text=item.annotation_thread.quote_text,
                position=(
                    TypeAdapter(ResearchPosition).validate_python(
                        item.annotation_thread.position
                    )
                    if item.annotation_thread.position is not None
                    else None
                ),
                color=AnnotationColor(item.annotation_thread.color),
                role=item.annotation_thread.role,
                mode=annotation_mode,
                comment_count=comment_count,
                last_activity_at=last_activity_at,
                status=AnnotationThreadStatus(item.annotation_thread.status),
                resolved_by=(
                    self._creator_response(
                        item.annotation_thread.resolved_by_id,
                        resolved_by,
                    )
                    if item.annotation_thread.resolved_by_id is not None
                    else None
                ),
                resolved_at=item.annotation_thread.resolved_at,
                capabilities=AnnotationThreadCapabilities(
                    reply=access.has_audience_access
                    and item.annotation_thread.status == "open",
                    recolor=access.can_manage,
                    resolve=access.can_resolve
                    and item.audience_type == ResearchAudienceType.PROJECT.value
                    and bool(item.annotation_thread.comments)
                    and item.annotation_thread.status == "open",
                    reopen=access.can_resolve
                    and item.annotation_thread.status == "resolved",
                    delete=can_delete_annotation,
                ),
                comments=[
                    self.serialize_comment(
                        comment,
                        user_id=user_id,
                        has_audience_access=access.has_audience_access,
                    )
                    for comment in item.annotation_thread.comments
                ],
            )
        elif item.citation is not None:
            citation = CitationContent(
                snapshot=CitationSnapshot.model_validate(item.citation.snapshot)
            )
        elif item.audio_overview is not None:
            audio = AudioOverviewContent.model_validate(
                {
                    "title": item.audio_overview.title,
                    "transcript": item.audio_overview.transcript,
                    "citations": item.audio_overview.citations,
                    "audio_url": s3_service.generate_presigned_url(
                        item.audio_overview.s3_object_key
                    ),
                    "voice_id": item.audio_overview.voice_id,
                    "model_version": item.audio_overview.model_version,
                }
            )
        elif item.data_table is not None:
            data_table = DataTableContent(
                title=item.data_table.title,
                columns=item.data_table.columns,
                rows=item.data_table.rows,
                citations=item.data_table.citations,
                row_failures=item.data_table.row_failures,
            )
        return ResearchItemResponse(
            id=item.id,
            kind=ResearchItemKind(item.kind),
            audience=audience,
            target_document_id=item.target_document_id,
            created_by=creator,
            created_at=item.created_at,
            updated_at=item.updated_at,
            capabilities=ResearchItemCapabilities(
                edit=access.can_manage,
                delete=(
                    can_delete_annotation
                    if item.annotation_thread is not None
                    else access.can_manage
                ),
            ),
            annotation_thread=annotation,
            citation=citation,
            audio_overview=audio,
            data_table=data_table,
        )

    def serialize_annotation_summary(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
        comment_count: int,
        last_activity_at: datetime,
        has_foreign_replies: bool,
        include_comments: bool = True,
    ) -> AnnotationThreadSummaryResponse:
        if item.annotation_thread is None or item.target_document_id is None:
            raise RuntimeError("annotation_summary_without_thread")
        access = research_item_policy.require_visible(
            db,
            item=item,
            user_id=user_id,
        )
        thread = item.annotation_thread
        audience: PersonalResearchAudience | ProjectResearchAudience
        if item.audience_type == ResearchAudienceType.PROJECT.value:
            if item.audience_project_id is None:
                raise RuntimeError("project_annotation_without_project")
            audience = ProjectResearchAudience(project_id=item.audience_project_id)
            mode = (
                AnnotationThreadMode.DISCUSSION
                if comment_count > 0
                else AnnotationThreadMode.HIGHLIGHT
            )
        else:
            audience = PersonalResearchAudience()
            mode = (
                AnnotationThreadMode.NOTE
                if comment_count > 0
                else AnnotationThreadMode.HIGHLIGHT
            )
        resolved_by = thread.resolved_by
        can_delete = access.can_manage and not has_foreign_replies
        return AnnotationThreadSummaryResponse(
            id=item.id,
            audience=audience,
            target_document_id=item.target_document_id,
            created_by=self._creator_response(
                item.created_by_id,
                item.created_by,
            ),
            created_at=item.created_at,
            quote_text=thread.quote_text,
            position=(
                TypeAdapter(ResearchPosition).validate_python(thread.position)
                if thread.position is not None
                else None
            ),
            color=AnnotationColor(thread.color),
            role=thread.role,
            mode=mode,
            comment_count=comment_count,
            last_activity_at=last_activity_at,
            status=AnnotationThreadStatus(thread.status),
            resolved_by=(
                self._creator_response(thread.resolved_by_id, resolved_by)
                if thread.resolved_by_id is not None
                else None
            ),
            resolved_at=thread.resolved_at,
            capabilities=AnnotationThreadCapabilities(
                reply=access.has_audience_access and thread.status == "open",
                recolor=access.can_manage,
                resolve=access.can_resolve
                and item.audience_type == ResearchAudienceType.PROJECT.value
                and comment_count > 0
                and thread.status == "open",
                reopen=access.can_resolve and thread.status == "resolved",
                delete=can_delete,
            ),
            comments=(
                [
                    self.serialize_comment(
                        comment,
                        user_id=user_id,
                        has_audience_access=access.has_audience_access,
                    )
                    for comment in thread.comments
                ]
                if include_comments
                else []
            ),
        )

    @staticmethod
    def serialize_comment(
        comment: AnnotationComment,
        *,
        user_id: int,
        has_audience_access: bool,
    ) -> AnnotationCommentResponse:
        can_manage = comment.created_by_id == user_id and has_audience_access
        return AnnotationCommentResponse(
            id=comment.id,
            thread_id=comment.thread_id,
            content=comment.content,
            role=comment.role,
            created_by=ResearchRepository._creator_response(
                comment.created_by_id,
                comment.created_by,
            ),
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            can_edit=can_manage,
            can_delete=can_manage,
        )


research_repository = ResearchRepository()
