"""Conversation message use case and replaceable streaming boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.turns import (
    ConversationTurnBranchCreateRequest,
    ConversationTurnCreateRequest,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationGenerationAccepted,
    ConversationGenerationCancellation,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from app.shared.domain.enums import ReasoningLevel

CONVERSATION_TURN_CREATED = OperationAction("conversation.turn_created")
CONVERSATION_RESPONSE_CREATED = OperationAction("conversation.response_created")
CONVERSATION_RESPONSE_COMPLETED = OperationAction("conversation.response_completed")
RESEARCH_CITATION_CREATED = OperationAction("research.citation_created")


@dataclass(frozen=True, slots=True)
class ChatHistoryMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatPaperSnapshot:
    document_id: UUID
    title: str | None
    abstract: str | None
    raw_content: str | None
    keywords: list[str] | None
    authors: list[str] | None
    publish_date: date | datetime | None


@dataclass(frozen=True, slots=True)
class ConversationChatScope:
    scope_type: ConversationScopeType
    project_id: UUID | None
    document_id: UUID | None
    paper_context: PaperCollection
    tool_permissions: frozenset[WorkspacePermission]
    title_is_default: bool


@dataclass(frozen=True, slots=True)
class MentionScope:
    snapshot: list[dict[str, JsonValue]] | None
    annotation_threads: list[dict[str, JsonValue]] | None


@dataclass(frozen=True, slots=True)
class ChatProjectSnapshot:
    project_id: UUID
    title: str
    description: str | None
    document_count: int


@dataclass(frozen=True, slots=True)
class ConversationContextSnapshot:
    papers: list[ChatPaperSnapshot]
    projects: list[ChatProjectSnapshot]
    available_document_count: int | None


@dataclass(frozen=True, slots=True)
class PersistedChatResponse:
    id: UUID
    turn_id: UUID
    variant_index: int
    status: str
    content: str
    references: dict[str, JsonValue] | None
    trace: ConversationTrace | None
    duration_ms: int | None
    failure: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class ConversationTurnStart:
    turn_id: UUID
    response: PersistedChatResponse
    turn_operation_id: UUID
    correlation_id: UUID
    turn_created: bool
    response_created: bool
    generation_kind: Literal["initial", "retry", "branch"]
    suggestions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversationTurnCompletion:
    response: PersistedChatResponse
    created: bool
    citation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ConversationBranchPreparation:
    request: ConversationTurnCreateRequest
    paper_context: PaperCollection


@dataclass(frozen=True, slots=True)
class ConversationGenerationPreparation:
    request: ConversationTurnCreateRequest
    turn_start: ConversationTurnStart
    paper_context: PaperCollection


class ConversationChatDataGateway(Protocol):
    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationChatScope: ...

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        before_turn_id: UUID,
    ) -> list[ChatHistoryMessage]: ...

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot: ...

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationTurnCreateRequest,
    ) -> MentionScope: ...

    def start_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
        user_content: str,
        contexts: list[dict[str, JsonValue]],
        paper_context: dict[str, JsonValue],
        reasoning_level: str,
        locale: str,
        time_zone: str,
        branch_from_turn_id: UUID | None,
        created_operation_id: UUID,
        correlation_id: UUID,
    ) -> ConversationTurnStart: ...

    def complete_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
        duration_ms: int,
        created_operation_id: UUID,
        correlation_id: UUID,
    ) -> ConversationTurnCompletion: ...

    def finish_response(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        response_id: UUID,
        status: str,
        duration_ms: int,
        failure: dict[str, JsonValue] | None = None,
    ) -> None: ...

    def save_turn_suggestions(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        suggestions: tuple[str, str, str],
    ) -> bool: ...

    def retry_request(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationTurnCreateRequest: ...

    def branch_request(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        source_turn_id: UUID,
        request: ConversationTurnBranchCreateRequest,
    ) -> ConversationBranchPreparation: ...

    def resume_generation(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> ConversationGenerationPreparation: ...

    def cancel_generation(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> PersistedChatResponse: ...


class ConversationChatData:
    """Short-transaction persistence boundary used by the streaming workflow."""

    def __init__(
        self,
        gateway: ConversationChatDataGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationChatScope:
        return self._gateway.prepare(
            actor=actor,
            conversation_id=conversation_id,
            paper_context_snapshot=paper_context_snapshot,
        )

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        before_turn_id: UUID,
    ) -> list[ChatHistoryMessage]:
        return self._gateway.history(
            actor=actor,
            conversation_id=conversation_id,
            before_turn_id=before_turn_id,
        )

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot:
        return self._gateway.context(actor=actor, scope=scope)

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationTurnCreateRequest,
    ) -> MentionScope:
        return self._gateway.mentions(
            actor=actor,
            request=request,
        )

    def start_turn(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
        user_content: str,
        contexts: list[dict[str, JsonValue]],
        paper_context: dict[str, JsonValue],
        reasoning_level: str,
        locale: str,
        time_zone: str,
        branch_from_turn_id: UUID | None = None,
    ) -> ConversationTurnStart:
        result = self._gateway.start_turn(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            generation_kind=generation_kind,
            user_content=user_content,
            contexts=contexts,
            paper_context=paper_context,
            reasoning_level=reasoning_level,
            locale=locale,
            time_zone=time_zone,
            branch_from_turn_id=branch_from_turn_id,
            created_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes: list[OperationChange] = []
        if result.turn_created:
            changes.append(
                OperationChange(
                    action=CONVERSATION_TURN_CREATED,
                    resources=(
                        ResourceRef("conversation", str(conversation_id)),
                        ResourceRef("conversation_turn", str(result.turn_id)),
                    ),
                )
            )
        if result.response_created:
            changes.append(
                OperationChange(
                    action=CONVERSATION_RESPONSE_CREATED,
                    resources=(
                        ResourceRef("conversation_turn", str(result.turn_id)),
                        ResourceRef("conversation_response", str(result.response.id)),
                    ),
                )
            )
        if changes:
            self._journal.append_many(
                actor=actor,
                operation=operation,
                changes=changes,
            )
        return result

    def complete_turn(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
        duration_ms: int,
    ) -> ConversationTurnCompletion:
        result = self._gateway.complete_turn(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            assistant_content=assistant_content,
            assistant_references=assistant_references,
            assistant_trace=assistant_trace,
            artifacts=artifacts,
            duration_ms=duration_ms,
            created_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        if result.created:
            changes = [
                OperationChange(
                    action=CONVERSATION_RESPONSE_COMPLETED,
                    resources=(
                        ResourceRef("conversation", str(conversation_id)),
                        ResourceRef("conversation_response", str(result.response.id)),
                    ),
                )
            ]
            changes.extend(
                OperationChange(
                    action=RESEARCH_CITATION_CREATED,
                    resources=(ResourceRef("research_item", str(citation_id)),),
                )
                for citation_id in result.citation_ids
            )
            self._journal.append_many(
                actor=actor,
                operation=operation,
                changes=changes,
            )
        return result

    def finish_response(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        response_id: UUID,
        status: str,
        duration_ms: int,
        failure: dict[str, JsonValue] | None = None,
    ) -> None:
        self._gateway.finish_response(
            actor=actor,
            conversation_id=conversation_id,
            response_id=response_id,
            status=status,
            duration_ms=duration_ms,
            failure=failure,
        )

    def save_turn_suggestions(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        suggestions: tuple[str, str, str],
    ) -> bool:
        return self._gateway.save_turn_suggestions(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            suggestions=suggestions,
        )

    def retry_request(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationTurnCreateRequest:
        return self._gateway.retry_request(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )

    def branch_request(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        source_turn_id: UUID,
        request: ConversationTurnBranchCreateRequest,
    ) -> ConversationBranchPreparation:
        return self._gateway.branch_request(
            actor=actor,
            conversation_id=conversation_id,
            source_turn_id=source_turn_id,
            request=request,
        )

    def resume_generation(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> ConversationGenerationPreparation:
        return self._gateway.resume_generation(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            generation_kind=generation_kind,
        )

    def cancel_generation(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> PersistedChatResponse:
        return self._gateway.cancel_generation(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )


class ConversationChatGateway(Protocol):
    async def accept_start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        conversation: ConversationCreateRequest,
        request: ConversationTurnCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted: ...

    async def accept(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry", "branch"] = "initial",
        branch_from_turn_id: UUID | None = None,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationGenerationAccepted: ...

    async def resume(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> AsyncIterator[str]: ...

    async def accept_retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        client_ip: str,
    ) -> ConversationGenerationAccepted: ...

    async def accept_branch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        source_turn_id: UUID,
        request: ConversationTurnBranchCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted: ...

    async def subscribe(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        last_event_id: str | None,
        include_assistant_candidates: bool = False,
    ) -> AsyncIterator[str]: ...

    async def cancel(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationGenerationCancellation: ...


class ConversationChat:
    def __init__(self, gateway: ConversationChatGateway) -> None:
        self._gateway = gateway

    async def accept_start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        conversation: ConversationCreateRequest,
        request: ConversationTurnCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        return await self._gateway.accept_start(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            conversation=conversation,
            request=request,
            client_ip=client_ip,
        )

    async def accept(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry", "branch"] = "initial",
        branch_from_turn_id: UUID | None = None,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationGenerationAccepted:
        return await self._gateway.accept(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind=generation_kind,
            branch_from_turn_id=branch_from_turn_id,
            paper_context_snapshot=paper_context_snapshot,
        )

    async def resume(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> AsyncIterator[str]:
        return await self._gateway.resume(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            generation_kind=generation_kind,
        )

    async def accept_retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        return await self._gateway.accept_retry(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            client_ip=client_ip,
        )

    async def accept_branch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        source_turn_id: UUID,
        request: ConversationTurnBranchCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        return await self._gateway.accept_branch(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            source_turn_id=source_turn_id,
            request=request,
            client_ip=client_ip,
        )

    async def subscribe(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        last_event_id: str | None,
        include_assistant_candidates: bool = False,
    ) -> AsyncIterator[str]:
        return await self._gateway.subscribe(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            last_event_id=last_event_id,
            include_assistant_candidates=include_assistant_candidates,
        )

    async def cancel(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationGenerationCancellation:
        return await self._gateway.cancel(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )

    @staticmethod
    def capabilities() -> dict[str, object]:
        return {
            "reasoning_levels": [
                {
                    "id": ReasoningLevel.STANDARD.value,
                    "label": "Standard",
                    "description": ("Fast, balanced reasoning for most questions."),
                },
                {
                    "id": ReasoningLevel.DEEP.value,
                    "label": "Deep",
                    "description": ("More thorough reasoning for complex questions."),
                },
            ],
            "default_reasoning_level": ReasoningLevel.STANDARD.value,
        }
