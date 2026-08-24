"""Research-item commands and queries independent of HTTP and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadListResponse,
    AnnotationThreadSummaryResponse,
    CreateAnnotationCommentRequest,
    CreateAnnotationThreadRequest,
    DeleteResearchItemResponse,
    ResearchItemListResponse,
    ResearchItemResponse,
    UpdateAnnotationCommentRequest,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.lifecycle import AnnotationThreadDeletionPlan
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import (
    AnnotationAudienceFilter,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchItemKind,
    RoleType,
)

RESEARCH_ANNOTATION_THREAD_CREATED = OperationAction(
    "research.annotation_thread_created"
)
RESEARCH_ANNOTATION_THREAD_UPDATED = OperationAction(
    "research.annotation_thread_updated"
)
RESEARCH_ANNOTATION_THREAD_DELETED = OperationAction(
    "research.annotation_thread_deleted"
)
RESEARCH_ANNOTATION_COMMENT_CREATED = OperationAction(
    "research.annotation_comment_created"
)
RESEARCH_ANNOTATION_COMMENT_UPDATED = OperationAction(
    "research.annotation_comment_updated"
)
RESEARCH_ANNOTATION_COMMENT_DELETED = OperationAction(
    "research.annotation_comment_deleted"
)
RESEARCH_ITEM_DELETED = OperationAction("research.item_deleted")


@dataclass(frozen=True, slots=True)
class ResearchItemChange[T]:
    value: T
    changed: bool


@dataclass(frozen=True, slots=True)
class AnnotationThreadSummaryKeyset:
    """Stable source-position key for one annotation summary row."""

    page_number: int | None
    anchor_y: float | None
    anchor_x: float | None
    start_offset: int | None
    end_offset: int | None
    created_at: datetime
    item_id: UUID


@dataclass(frozen=True, slots=True)
class AnnotationThreadSummaryPage:
    items: list[AnnotationThreadSummaryResponse]
    next_keyset: AnnotationThreadSummaryKeyset | None


@dataclass(frozen=True, slots=True)
class ResearchItemPageAccess:
    """Authorized scalar facts for one bounded, revision-keyed full read."""

    item_id: UUID
    kind: ResearchItemKind
    revision: str
    durable_json_utf8_upper_bound: int
    access_url: str | None = None
    legacy_payload_json_utf8_upper_bound: int | None = None


@dataclass(frozen=True, slots=True)
class LegacyResearchDocumentPage:
    """Historical paper-scoped output page prepared under one locked snapshot."""

    items: list[ResearchItemResponse]
    total_count: int


class ResearchItemGateway(Protocol):
    def authorize_page(
        self,
        *,
        user_id: int,
        item_id: UUID,
    ) -> ResearchItemPageAccess: ...

    def lock_legacy_read(
        self,
        *,
        user_id: int,
        item_id: UUID,
    ) -> ResearchItemPageAccess: ...

    def get_item(self, *, user_id: int, item_id: UUID) -> ResearchItemResponse: ...

    def get_comment(
        self, *, user_id: int, comment_id: UUID
    ) -> AnnotationCommentResponse: ...

    def list_document(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        annotations_only: bool,
    ) -> list[ResearchItemResponse]: ...

    def list_document_legacy(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        limit: int,
        maximum_payload_json_bytes: int,
    ) -> LegacyResearchDocumentPage: ...

    def list_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ResearchItemResponse]: ...

    def list_annotation_threads(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
    ) -> list[AnnotationThreadSummaryResponse]: ...

    def list_annotation_thread_summaries_page(
        self,
        *,
        user_id: int,
        document_id: UUID,
        project_id: UUID | None,
        audience: AnnotationAudienceFilter | None,
        mode: AnnotationThreadMode | None,
        status: AnnotationThreadStatus,
        after: AnnotationThreadSummaryKeyset | None,
        limit: int,
    ) -> AnnotationThreadSummaryPage: ...

    def get_annotation_thread(
        self,
        *,
        user_id: int,
        thread_id: UUID,
    ) -> ResearchItemResponse: ...

    def plan_annotation_thread_delete(
        self,
        *,
        user_id: int,
        thread_id: UUID,
    ) -> AnnotationThreadDeletionPlan: ...

    def create_annotation_thread(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: CreateAnnotationThreadRequest,
        content_role: RoleType,
    ) -> ResearchItemResponse: ...

    def update_annotation_thread(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateAnnotationThreadRequest,
    ) -> ResearchItemChange[ResearchItemResponse]: ...

    def update_annotation_thread_bounded(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateAnnotationThreadRequest,
    ) -> ResearchItemChange[ResearchItemResponse]: ...

    def delete_item(
        self,
        *,
        user_id: int,
        item_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> None: ...

    def create_comment(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
        content_role: RoleType,
    ) -> AnnotationCommentResponse: ...

    def update_comment(
        self,
        *,
        user_id: int,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> ResearchItemChange[AnnotationCommentResponse]: ...

    def delete_comment(self, *, user_id: int, comment_id: UUID) -> None: ...


class ResearchItems:
    def __init__(
        self,
        gateway: ResearchItemGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def authorize_page(
        self,
        *,
        actor: Actor,
        item_id: UUID,
    ) -> ResearchItemPageAccess:
        return self._gateway.authorize_page(user_id=actor.id, item_id=item_id)

    def lock_legacy_read(
        self,
        *,
        actor: Actor,
        item_id: UUID,
    ) -> ResearchItemPageAccess:
        return self._gateway.lock_legacy_read(user_id=actor.id, item_id=item_id)

    def get_item(self, *, actor: Actor, item_id: UUID) -> ResearchItemResponse:
        return self._gateway.get_item(user_id=actor.id, item_id=item_id)

    def get_comment(
        self, *, actor: Actor, comment_id: UUID
    ) -> AnnotationCommentResponse:
        return self._gateway.get_comment(user_id=actor.id, comment_id=comment_id)

    def list_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
        annotations_only: bool = False,
    ) -> ResearchItemListResponse:
        return ResearchItemListResponse(
            items=self._gateway.list_document(
                user_id=actor.id,
                document_id=document_id,
                project_id=project_id,
                annotations_only=annotations_only,
            )
        )

    def list_document_legacy(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        limit: int,
        maximum_payload_json_bytes: int,
    ) -> LegacyResearchDocumentPage:
        return self._gateway.list_document_legacy(
            user_id=actor.id,
            document_id=document_id,
            project_id=project_id,
            query=query,
            kinds=kinds,
            limit=limit,
            maximum_payload_json_bytes=maximum_payload_json_bytes,
        )

    def list_project(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ResearchItemListResponse:
        return ResearchItemListResponse(
            items=self._gateway.list_project(
                user_id=actor.id,
                project_id=project_id,
            )
        )

    def list_annotation_threads(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
        audience: AnnotationAudienceFilter | None = None,
        mode: AnnotationThreadMode | None = None,
        status: AnnotationThreadStatus = AnnotationThreadStatus.OPEN,
    ) -> AnnotationThreadListResponse:
        return AnnotationThreadListResponse(
            items=self._gateway.list_annotation_threads(
                user_id=actor.id,
                document_id=document_id,
                project_id=project_id,
                audience=audience,
                mode=mode,
                status=status,
            )
        )

    def list_annotation_thread_summaries_page(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
        audience: AnnotationAudienceFilter | None = None,
        mode: AnnotationThreadMode | None = None,
        status: AnnotationThreadStatus = AnnotationThreadStatus.OPEN,
        after: AnnotationThreadSummaryKeyset | None = None,
        limit: int,
    ) -> AnnotationThreadSummaryPage:
        return self._gateway.list_annotation_thread_summaries_page(
            user_id=actor.id,
            document_id=document_id,
            project_id=project_id,
            audience=audience,
            mode=mode,
            status=status,
            after=after,
            limit=limit,
        )

    def get_annotation_thread(
        self,
        *,
        actor: Actor,
        thread_id: UUID,
    ) -> ResearchItemResponse:
        return self._gateway.get_annotation_thread(
            user_id=actor.id,
            thread_id=thread_id,
        )

    def plan_annotation_thread_delete(
        self,
        *,
        actor: Actor,
        thread_id: UUID,
    ) -> AnnotationThreadDeletionPlan:
        return self._gateway.plan_annotation_thread_delete(
            user_id=actor.id,
            thread_id=thread_id,
        )

    def create_annotation_thread(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: CreateAnnotationThreadRequest,
        content_role: RoleType,
    ) -> ResearchItemResponse:
        if not isinstance(content_role, RoleType):
            raise TypeError("content_role must be a RoleType")
        result = self._gateway.create_annotation_thread(
            user_id=actor.id,
            document_id=document_id,
            request=request,
            content_role=content_role,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_THREAD_CREATED,
            resources=(ResourceRef("research_item", str(result.id)),),
        )
        return result

    def update_annotation_thread(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: UpdateAnnotationThreadRequest,
    ) -> ResearchItemResponse:
        result = self._gateway.update_annotation_thread(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_ANNOTATION_THREAD_UPDATED,
                resources=(ResourceRef("research_item", str(thread_id)),),
            )
        return result.value

    def update_annotation_thread_bounded(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: UpdateAnnotationThreadRequest,
    ) -> ResearchItemResponse:
        """Update a thread and return the bounded Agent mutation projection."""

        result = self._gateway.update_annotation_thread_bounded(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_ANNOTATION_THREAD_UPDATED,
                resources=(ResourceRef("research_item", str(thread_id)),),
            )
        return result.value

    def delete_annotation_thread(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=thread_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_THREAD_DELETED,
            resources=(ResourceRef("research_item", str(thread_id)),),
        )
        return DeleteResearchItemResponse()

    def create_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
        content_role: RoleType,
    ) -> AnnotationCommentResponse:
        if not isinstance(content_role, RoleType):
            raise TypeError("content_role must be a RoleType")
        result = self._gateway.create_comment(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
            content_role=content_role,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_COMMENT_CREATED,
            resources=(ResourceRef("annotation_comment", str(result.id)),),
        )
        return result

    def update_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        result = self._gateway.update_comment(
            user_id=actor.id,
            comment_id=comment_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_ANNOTATION_COMMENT_UPDATED,
                resources=(ResourceRef("annotation_comment", str(comment_id)),),
            )
        return result.value

    def delete_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        comment_id: UUID,
    ) -> None:
        self._gateway.delete_comment(user_id=actor.id, comment_id=comment_id)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_COMMENT_DELETED,
            resources=(ResourceRef("annotation_comment", str(comment_id)),),
        )

    def delete_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item_id: UUID,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=item_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ITEM_DELETED,
            resources=(ResourceRef("research_item", str(item_id)),),
        )
        return DeleteResearchItemResponse()
