"""Explicit persistence and visibility queries for typed research items."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.models import (
    AnnotationComment,
    AnnotationColor,
    AnnotationThread,
    AnnotationThreadStatus,
    AuthUser,
    CitationOutput,
    Conversation,
    ConversationScopeType,
    ResearchAudienceType,
    ResearchItem,
    ResearchItemKind,
    RoleType,
)
from app.shared.domain.enums import AnnotationAudienceFilter, AnnotationThreadMode
from app.shared.domain import AppError, FailureKind
from app.helpers.s3 import s3_service
from app.modules.papers.infrastructure.access import require_document_access
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
from app.modules.research.application.positions import (
    ResearchPosition,
    position_columns,
)
from pydantic import TypeAdapter
from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload

_CITATION_SNAPSHOTS = TypeAdapter(list[CitationSnapshot])


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


class ResearchRepository:
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
            statement = statement.with_for_update()
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
            self.serialize_annotation_summary(
                db,
                item=item,
                user_id=user_id,
                comment_count=int(count),
                last_activity_at=last_activity_at_value,
                has_foreign_replies=int(foreign_count) > 0,
            )
            for item, count, last_activity_at_value, foreign_count in db.execute(
                statement
            ).unique()
        ]

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
        require_document_access(db, document_id=document_id, user_id=user_id)
        if create.audience_type not in {
            ResearchAudienceType.PERSONAL,
            ResearchAudienceType.PROJECT,
        }:
            raise ValueError("annotation audience must be personal or project")
        if create.audience_type is ResearchAudienceType.PROJECT:
            from app.modules.projects.infrastructure.access import (
                require_project_access,
            )
            from app.modules.projects.infrastructure.models import ProjectPaper

            if create.audience_project_id is None:
                raise ValueError("project annotation requires audience_project_id")
            require_project_access(
                db, project_id=create.audience_project_id, user_id=user_id
            )
            if (
                db.scalar(
                    select(ProjectPaper.id).where(
                        ProjectPaper.project_id == create.audience_project_id,
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
        item = self.require_visible(db, item_id=thread_id, user_id=user_id)
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
        if item.annotation_thread is None:
            raise RuntimeError("annotation_item_without_thread")
        if item.annotation_thread.status == "resolved":
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
            statement = statement.with_for_update()
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
            if next_status == "resolved" and not item.annotation_thread.comments:
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
        db.flush()
        db.refresh(item)
        return ResearchItemWrite(value=item, changed=True)

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
            comments=[
                self.serialize_comment(
                    comment,
                    user_id=user_id,
                    has_audience_access=access.has_audience_access,
                )
                for comment in thread.comments
            ],
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
