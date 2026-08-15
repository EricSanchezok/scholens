"""SQLAlchemy, LLM, and telemetry adapters for Conversation use cases."""

from __future__ import annotations

from uuid import UUID

from app.database.models import Conversation
from app.modules.conversations.application.contracts.conversations import (
    ConversationBranchSelectionRequest,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
    PaperContext,
    ConversationResponseVariantResponse,
)
from app.modules.conversations.application.conversations import (
    ConversationChange,
    ConversationListPosition,
    ConversationPage,
    ConversationTurnsPage,
)
from app.shared.domain.enums import ConversationScopeType
from app.modules.conversations.infrastructure.presenters import (
    serialize_response,
    serialize_turns,
)
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.bootstrap.adapters.conversation_repository import conversation_repository
from sqlalchemy.orm import Session
from pydantic import TypeAdapter


_PAPER_CONTEXT: TypeAdapter[PaperContext] = TypeAdapter(PaperContext)


class SqlAlchemyConversationGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _detail(
        self,
        *,
        conversation: Conversation,
        user_id: int,
    ) -> ConversationDetailResponse:
        summary = conversation_repository.summarize(
            self._db,
            conversation=conversation,
        )
        return ConversationDetailResponse(
            **summary.model_dump(),
            paper_context=conversation_repository.paper_context(
                self._db,
                conversation=conversation,
                user_id=user_id,
            ),
            tool_permissions=conversation_repository.tool_permissions(conversation),
        )

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
    ) -> ConversationPage:
        conversations, has_more = conversation_repository.list(
            self._db,
            user_id=user_id,
            archived=archived,
            scope_type=scope_type,
            scope_id=scope_id,
            context_document_id=context_document_id,
            position=position,
            limit=limit,
        )
        return ConversationPage(
            items=[
                conversation_repository.summarize(
                    self._db,
                    conversation=conversation,
                )
                for conversation in conversations
            ],
            next_position=(
                ConversationListPosition(
                    pinned_at=conversations[-1].pinned_at,
                    updated_at=conversations[-1].updated_at,
                    conversation_id=conversations[-1].id,
                )
                if has_more and conversations
                else None
            ),
        )

    def create(
        self,
        *,
        user_id: int,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse:
        conversation = conversation_repository.create(
            self._db,
            request=request,
            user_id=user_id,
        )
        return self._detail(conversation=conversation, user_id=user_id)

    def get(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
    ) -> ConversationDetailResponse:
        conversation = conversation_repository.require_owned(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return self._detail(conversation=conversation, user_id=user_id)

    def turns(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> ConversationTurnsPage:
        conversation, turns = turn_repository.list_turns(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            offset=offset,
            limit=limit,
        )
        return ConversationTurnsPage(
            items=serialize_turns(
                turns,
                active_leaf_id=(turns[-1].id if offset == 0 and turns else None),
                branch_groups=turn_repository.branch_groups(
                    self._db,
                    conversation_id=conversation_id,
                ),
            ),
            path_revision=conversation.path_revision,
        )

    def select_branch(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationBranchSelectionRequest,
    ) -> ConversationChange[ConversationTurnsPage]:
        conversation, path, path_changed = turn_repository.select_branch(
            self._db,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            user_id=user_id,
        )
        context_changed = False
        if path:
            context_changed = conversation_repository.update_paper_context(
                self._db,
                conversation_id=conversation_id,
                user_id=user_id,
                request=_PAPER_CONTEXT.validate_python(path[-1].paper_context),
            ).changed
        return ConversationChange(
            value=ConversationTurnsPage(
                items=serialize_turns(
                    path,
                    active_leaf_id=path[-1].id if path else None,
                    branch_groups=turn_repository.branch_groups(
                        self._db,
                        conversation_id=conversation_id,
                    ),
                ),
                path_revision=conversation.path_revision,
            ),
            changed=path_changed or context_changed,
        )

    def select_response(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationResponseVariantResponse:
        return serialize_response(
            turn_repository.select_response(
                self._db,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
                user_id=user_id,
            )
        )

    def update(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationChange[ConversationSummaryResponse]:
        result = conversation_repository.update(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(
            value=conversation_repository.summarize(
                self._db,
                conversation=result.value,
            ),
            changed=result.changed,
        )

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationChange[ConversationSummaryResponse]:
        result = conversation_repository.move(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(
            value=conversation_repository.summarize(
                self._db,
                conversation=result.value,
            ),
            changed=result.changed,
        )

    def delete(self, *, user_id: int, conversation_id: UUID) -> None:
        conversation_repository.delete(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    def update_paper_context(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: PaperContext,
    ) -> ConversationChange[PaperContext]:
        result = conversation_repository.update_paper_context(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(value=result.value, changed=result.changed)

    def update_tool_permissions(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationChange[ConversationToolPermissionsResponse]:
        result = conversation_repository.update_tool_permissions(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(value=result.value, changed=result.changed)

    def apply_initial_generated_title(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        return conversation_repository.apply_initial_generated_title(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            title=title,
        )
