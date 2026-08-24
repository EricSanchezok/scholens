"""Conversation lifecycle and history use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationBranchSelectionRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationListRequest,
    ConversationTurnsResponse,
    ConversationResponseVariantResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
    PaperContext,
    ConversationTurnResponse,
)
from app.shared.application import Actor, OperationContext, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ConversationScopeType

CONVERSATION_CREATED = OperationAction("conversation.created")
CONVERSATION_UPDATED = OperationAction("conversation.updated")
CONVERSATION_MOVED = OperationAction("conversation.moved")
CONVERSATION_TITLE_UPDATED = OperationAction("conversation.title_updated")
CONVERSATION_DELETED = OperationAction("conversation.deleted")
CONVERSATION_PAPER_CONTEXT_UPDATED = OperationAction(
    "conversation.paper_context_updated"
)
CONVERSATION_TOOL_PERMISSIONS_UPDATED = OperationAction(
    "conversation.tool_permissions_updated"
)
CONVERSATION_RESPONSE_SELECTED = OperationAction("conversation.response_selected")
CONVERSATION_BRANCH_SELECTED = OperationAction("conversation.branch_selected")


@dataclass(frozen=True, slots=True)
class ConversationChange[T]:
    value: T
    changed: bool


@dataclass(frozen=True, slots=True)
class ConversationListPosition:
    pinned_at: datetime | None
    updated_at: datetime
    conversation_id: UUID


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: list[ConversationSummaryResponse]
    next_position: ConversationListPosition | None


@dataclass(frozen=True, slots=True)
class ConversationTurnsPage:
    items: list[ConversationTurnResponse]
    path_revision: int


class ConversationGateway(Protocol):
    def list_conversations(
        self,
        *,
        user_id: int,
        archived: bool,
        scope_type: ConversationScopeType | None,
        scope_id: UUID | None,
        context_document_id: UUID | None,
        position: ConversationListPosition | None,
        limit: int,
    ) -> ConversationPage: ...

    def create(
        self,
        *,
        user_id: int,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse: ...

    def create_with_id(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationCreateRequest,
    ) -> ConversationChange[ConversationDetailResponse]: ...

    def get(
        self, *, user_id: int, conversation_id: UUID
    ) -> ConversationDetailResponse: ...

    def turns(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> ConversationTurnsPage: ...

    def select_branch(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationBranchSelectionRequest,
    ) -> ConversationChange[ConversationTurnsPage]: ...

    def select_response(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationResponseVariantResponse: ...

    def update(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationChange[ConversationSummaryResponse]: ...

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationChange[ConversationSummaryResponse]: ...

    def delete(self, *, user_id: int, conversation_id: UUID) -> None: ...

    def update_paper_context(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: PaperContext,
    ) -> ConversationChange[PaperContext]: ...

    def update_tool_permissions(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationChange[ConversationToolPermissionsResponse]: ...

    def apply_initial_generated_title(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        title: str,
    ) -> bool: ...


class Conversations:
    def __init__(
        self,
        *,
        gateway: ConversationGateway,
        list_cursors: SignedCursorCodec,
        turn_cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._list_cursors = list_cursors
        self._turn_cursors = turn_cursors
        self._journal = journal

    def list_page(
        self,
        *,
        actor: Actor,
        request: ConversationListRequest,
    ) -> ConversationListResponse:
        fingerprint = json.dumps(
            {
                "actor_id": actor.id,
                "archived": request.archived,
                "scope_type": request.scope_type.value if request.scope_type else None,
                "scope_id": str(request.scope_id) if request.scope_id else None,
                "context_document_id": (
                    str(request.context_document_id)
                    if request.context_document_id
                    else None
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        position: ConversationListPosition | None = None
        if request.cursor:
            values = self._list_cursors.decode_keyset(
                cursor=request.cursor,
                fingerprint=fingerprint,
                arity=3,
            )
            try:
                position = ConversationListPosition(
                    pinned_at=datetime.fromisoformat(values[0]) if values[0] else None,
                    updated_at=datetime.fromisoformat(values[1]),
                    conversation_id=UUID(values[2]),
                )
            except ValueError as exc:
                raise AppError(
                    code="conversation_cursor_expired",
                    message="Conversation cursor is invalid or expired",
                    kind=FailureKind.CONFLICT,
                ) from exc
        page = self._gateway.list_conversations(
            user_id=actor.id,
            archived=request.archived,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            context_document_id=request.context_document_id,
            position=position,
            limit=request.limit,
        )
        next_cursor = None
        if page.next_position is not None:
            next_cursor = self._list_cursors.encode_keyset(
                fingerprint=fingerprint,
                values=(
                    page.next_position.pinned_at.isoformat()
                    if page.next_position.pinned_at
                    else "",
                    page.next_position.updated_at.isoformat(),
                    str(page.next_position.conversation_id),
                ),
            )
        return ConversationListResponse(
            items=page.items,
            next_cursor=next_cursor,
        )

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse:
        result = self._gateway.create(user_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_CREATED,
            resources=(ResourceRef("conversation", str(result.id)),),
        )
        return result

    def create_with_id(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationCreateRequest,
    ) -> ConversationChange[ConversationDetailResponse]:
        """Create a client-identified Conversation or return its owned row."""
        result = self._gateway.create_with_id(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_CREATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result

    def get(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
    ) -> ConversationDetailResponse:
        return self._gateway.get(
            user_id=actor.id,
            conversation_id=conversation_id,
        )

    def turns(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> ConversationTurnsResponse:
        fingerprint = f"{actor.id}:{conversation_id}:{limit}"
        requested_revision: int | None = None
        offset = 0
        if cursor:
            values = self._turn_cursors.decode_keyset(
                cursor=cursor,
                fingerprint=fingerprint,
                arity=2,
            )
            try:
                requested_revision = int(values[0])
                offset = int(values[1])
            except ValueError as exc:
                raise AppError(
                    code="conversation_cursor_expired",
                    message="Conversation cursor is invalid or expired",
                    kind=FailureKind.CONFLICT,
                ) from exc
        page = self._gateway.turns(
            user_id=actor.id,
            conversation_id=conversation_id,
            offset=offset,
            limit=limit + 1,
        )
        if requested_revision is not None and requested_revision != page.path_revision:
            raise AppError(
                code="conversation_path_changed",
                message="The selected conversation branch changed",
                kind=FailureKind.CONFLICT,
            )
        turns = page.items
        has_more = len(turns) > limit
        if has_more:
            # The gateway returns chronological order, so discard the oldest
            # extra item that belongs to the next, older page.
            turns = turns[1:]
        return ConversationTurnsResponse(
            items=turns,
            path_revision=page.path_revision,
            next_cursor=(
                self._turn_cursors.encode_keyset(
                    fingerprint=fingerprint,
                    values=(str(page.path_revision), str(offset + limit)),
                )
                if has_more
                else None
            ),
        )

    def select_branch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationBranchSelectionRequest,
    ) -> ConversationTurnsResponse:
        result = self._gateway.select_branch(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_BRANCH_SELECTED,
                resources=(
                    ResourceRef("conversation", str(conversation_id)),
                    ResourceRef("conversation_turn", str(request.turn_id)),
                ),
            )
        page = result.value
        return ConversationTurnsResponse(
            items=page.items,
            path_revision=page.path_revision,
        )

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationSummaryResponse:
        result = self._gateway.update(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def select_response(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationResponseVariantResponse:
        response = self._gateway.select_response(
            user_id=actor.id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_RESPONSE_SELECTED,
            resources=(
                ResourceRef("conversation", str(conversation_id)),
                ResourceRef("conversation_turn", str(turn_id)),
                ResourceRef("conversation_response", str(response_id)),
            ),
        )
        return response

    def move(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationSummaryResponse:
        result = self._gateway.move(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_MOVED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def apply_initial_generated_title(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        title: str,
    ) -> None:
        if self._gateway.apply_initial_generated_title(
            user_id=actor.id,
            conversation_id=conversation_id,
            title=title,
        ):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_TITLE_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )

    def delete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
    ) -> None:
        self._gateway.delete(
            user_id=actor.id,
            conversation_id=conversation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_DELETED,
            resources=(ResourceRef("conversation", str(conversation_id)),),
        )

    def update_paper_context(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: PaperContext,
    ) -> PaperContext:
        result = self._gateway.update_paper_context(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_PAPER_CONTEXT_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def update_tool_permissions(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationToolPermissionsResponse:
        result = self._gateway.update_tool_permissions(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_TOOL_PERMISSIONS_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value
