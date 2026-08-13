"""SQLAlchemy adapter for typed Research items."""

from __future__ import annotations

from uuid import UUID

from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadSummaryResponse,
    CreateAnnotationCommentRequest,
    CreateAnnotationThreadRequest,
    ResearchItemResponse,
    UpdateAnnotationCommentRequest,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.items import ResearchItemChange
from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.shared.domain.enums import (
    AnnotationAudienceFilter,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchItemKind,
    ResearchAudienceType,
    RoleType,
)
from sqlalchemy.orm import Session


class SqlAlchemyResearchItemGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _serialize(self, *, item: object, user_id: int) -> ResearchItemResponse:
        from app.modules.research.infrastructure.models import ResearchItem

        if not isinstance(item, ResearchItem):
            raise TypeError("expected ResearchItem")
        return research_repository.serialize(self._db, item=item, user_id=user_id)

    def list_document(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        annotations_only: bool,
    ) -> list[ResearchItemResponse]:
        return [
            self._serialize(item=item, user_id=user_id)
            for item in research_repository.list_for_document(
                self._db,
                document_id=document_id,
                user_id=user_id,
                project_id=project_id,
                kind=(ResearchItemKind.ANNOTATION_THREAD if annotations_only else None),
            )
        ]

    def list_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ResearchItemResponse]:
        return [
            self._serialize(item=item, user_id=user_id)
            for item in research_repository.list_for_project(
                self._db,
                project_id=project_id,
                user_id=user_id,
            )
        ]

    def list_annotation_threads(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
    ) -> list[AnnotationThreadSummaryResponse]:
        return research_repository.list_annotation_summaries(
            self._db,
            document_id=document_id,
            user_id=user_id,
            project_id=project_id,
            audience=audience,
            mode=mode,
            status=status,
        )

    def get_annotation_thread(
        self,
        *,
        user_id: int,
        thread_id: UUID,
    ) -> ResearchItemResponse:
        return self._serialize(
            item=research_repository.get_annotation_thread(
                self._db,
                thread_id=thread_id,
                user_id=user_id,
            ),
            user_id=user_id,
        )

    def create_annotation_thread(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: CreateAnnotationThreadRequest,
        content_role: RoleType,
    ) -> ResearchItemResponse:
        item = research_repository.create_annotation_thread(
            self._db,
            document_id=document_id,
            user_id=user_id,
            create=AnnotationThreadCreate(
                quote_text=request.quote_text,
                position=request.position,
                color=request.color.value,
                audience_type=ResearchAudienceType(request.audience.kind),
                audience_project_id=getattr(request.audience, "project_id", None),
                content_role=content_role,
                initial_comment=request.initial_comment,
            ),
        )
        return self._serialize(item=item, user_id=user_id)

    def update_annotation_thread(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateAnnotationThreadRequest,
    ) -> ResearchItemChange[ResearchItemResponse]:
        result = research_repository.update_annotation_thread(
            self._db,
            thread_id=thread_id,
            user_id=user_id,
            values=request.model_dump(exclude_unset=True),
        )
        return ResearchItemChange(
            value=self._serialize(item=result.value, user_id=user_id),
            changed=result.changed,
        )

    def delete_item(
        self,
        *,
        user_id: int,
        item_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> None:
        research_repository.delete_item(
            self._db,
            item_id=item_id,
            user_id=user_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _comment(
        *,
        comment: object,
        user_id: int,
    ) -> AnnotationCommentResponse:
        from app.modules.research.infrastructure.models import AnnotationComment

        if not isinstance(comment, AnnotationComment):
            raise TypeError("expected AnnotationComment")
        return research_repository.serialize_comment(
            comment,
            user_id=user_id,
            has_audience_access=True,
        )

    def create_comment(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
        content_role: RoleType,
    ) -> AnnotationCommentResponse:
        return self._comment(
            comment=research_repository.add_comment(
                self._db,
                thread_id=thread_id,
                user_id=user_id,
                content=request.content,
                content_role=content_role,
            ),
            user_id=user_id,
        )

    def update_comment(
        self,
        *,
        user_id: int,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> ResearchItemChange[AnnotationCommentResponse]:
        result = research_repository.update_comment(
            self._db,
            comment_id=comment_id,
            user_id=user_id,
            content=request.content,
        )
        return ResearchItemChange(
            value=self._comment(
                comment=result.value,
                user_id=user_id,
            ),
            changed=result.changed,
        )

    def delete_comment(self, *, user_id: int, comment_id: UUID) -> None:
        research_repository.delete_comment(
            self._db,
            comment_id=comment_id,
            user_id=user_id,
        )
