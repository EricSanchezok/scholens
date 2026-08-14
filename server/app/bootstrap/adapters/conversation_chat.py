"""Public Conversation streaming adapter for the single Scholens agent."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Literal, Protocol

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency,
)
from app.llm.conversation_agent import (
    ConversationAgentResult,
    ScholensConversationAgent,
)
from app.llm.conversation_titles import (
    initial_conversation_title_generator,
)
from app.llm.follow_up_suggestions import SuggestionSeed
from app.llm.token_credits import llm_usage_context
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationTurnCreateRequest,
    ConversationStreamAssistantItemCompleteEvent,
    ConversationStreamAssistantItemDeltaEvent,
    ConversationStreamAssistantItemStartEvent,
    ConversationStreamCompleteEvent,
    ConversationStreamReferencesEvent,
    ConversationStreamResponseReadyEvent,
    ConversationStreamStartEvent,
    ConversationStreamSuggestionsEvent,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.modules.conversations.application.contracts.conversations import (
    ConversationTurnResponse,
)
from app.modules.conversations.application.chat import ChatHistoryMessage
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_stable_error,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import JsonValue
from pydantic import TypeAdapter
from scholens_observability import DiagnosticSnapshotRecorder

logger = logging.getLogger(__name__)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, JsonValue]])
_SUGGESTION_TAIL_SECONDS = 2.0


class ConversationSuggestionGenerator(Protocol):
    async def generate(self, seed: SuggestionSeed) -> list[str]: ...


def _validated_suggestions(values: list[str]) -> tuple[str, str, str]:
    normalized = [" ".join(value.split()).strip() for value in values]
    if (
        len(normalized) != 3
        or any(not value or len(value) > 160 for value in normalized)
        or len({value.casefold() for value in normalized}) != 3
    ):
        raise ValueError("suggestion generator must return three unique values")
    return normalized[0], normalized[1], normalized[2]


def _recent_selected_turns(
    history: list[ChatHistoryMessage],
) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(history) - 1, 2):
        user = history[index]
        assistant = history[index + 1]
        if user.role == "user" and assistant.role == "assistant":
            pairs.append((user.content, assistant.content))
    return tuple(pairs[-3:])


def _latest_turn_snapshot(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    actor: Actor,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
) -> ConversationTurnResponse:
    page = executor.query(
        lambda capabilities: capabilities.conversations.turns(
            actor=actor,
            conversation_id=conversation_id,
            cursor=None,
            limit=1,
        )
    )
    if not page.items or page.items[-1].id != turn_id:
        raise RuntimeError("persisted conversation turn snapshot is unavailable")
    return page.items[-1]


async def _generate_turn_suggestions(
    *,
    generator: ConversationSuggestionGenerator,
    seed: SuggestionSeed,
    executor: ApplicationExecutor[ApplicationCapabilities],
    actor: Actor,
    conversation_id: uuid.UUID,
) -> tuple[str, str, str] | None:
    try:
        suggestions = _validated_suggestions(await generator.generate(seed))
        saved = await asyncio.to_thread(
            executor.command,
            lambda capabilities: (
                capabilities.conversation_chat_data.save_turn_suggestions(
                    actor=actor,
                    conversation_id=conversation_id,
                    turn_id=seed.turn_id,
                    suggestions=suggestions,
                )
            ),
        )
        return suggestions if saved else None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(
            "conversation.suggestions.generation_failed",
            extra={
                "turn_id": str(seed.turn_id),
                "error_type": type(exc).__name__,
            },
        )
        return None


async def _generate_initial_title(
    *,
    user_query: str,
    conversation_id: uuid.UUID,
) -> str | None:
    try:
        return await asyncio.to_thread(
            initial_conversation_title_generator.generate,
            [ChatHistoryMessage(role="user", content=user_query)],
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "conversation.title_generation.failed",
            extra={"conversation_id": str(conversation_id)},
        )
        return None


async def _apply_initial_title(
    *,
    title: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    actor: Actor,
    conversation_id: uuid.UUID,
    operation: OperationContext,
    operation_factory: OperationContextFactory,
) -> None:
    title_operation = operation_factory.resume(
        correlation_id=operation.trace.correlation_id,
        causation_id=operation.trace.operation_id,
        initiated_by=OperationInitiator.AGENT,
        origin=operation.origin,
        credential=operation.credential,
    )
    await asyncio.to_thread(
        executor.command,
        lambda capabilities: capabilities.conversations.apply_initial_generated_title(
            actor=actor,
            operation=title_operation,
            conversation_id=conversation_id,
            title=title,
        ),
    )


async def stream_conversation_agent(
    request: ConversationTurnCreateRequest,
    *,
    conversation_id: uuid.UUID,
    client_ip: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    current_user: Actor,
    runtime: ScholensConversationAgent,
    operation: OperationContext,
    operation_factory: OperationContextFactory,
    suggestion_generator: ConversationSuggestionGenerator,
    generation_kind: Literal["initial", "retry"] = "initial",
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
) -> AsyncGenerator[str, None]:
    """Run one contextual agent and expose its sanitized product event stream."""
    conversation_scope = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.prepare(
            actor=current_user,
            conversation_id=conversation_id,
        )
    )
    project_id = conversation_scope.project_id
    mentions = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.mentions(
            actor=current_user,
            request=request,
        )
    )
    context_snapshot = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.context(
            actor=current_user,
            scope=conversation_scope,
        )
    )

    scope_snapshot: list[dict[str, JsonValue]] = []
    if conversation_scope.paper_context.kind == "library":
        scope_snapshot.append({"kind": "library", "id": "library", "title": "Library"})
    else:
        scope_snapshot.extend(
            {
                "kind": "project",
                "id": str(project.project_id),
                "title": project.title,
            }
            for project in context_snapshot.projects
        )
        scope_snapshot.extend(
            {
                "kind": "paper",
                "id": str(paper.document_id),
                "title": paper.title,
            }
            for paper in context_snapshot.papers
        )
    if mentions.snapshot is not None:
        scope_snapshot.extend(mentions.snapshot)

    serialized_contexts = [
        context.model_dump(mode="json") for context in request.contexts
    ]
    turn_start = executor.command(
        lambda capabilities: capabilities.conversation_chat_data.start_turn(
            actor=current_user,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            generation_kind=generation_kind,
            user_content=request.user_query,
            contexts=_JSON_OBJECT_LIST.validate_python(serialized_contexts),
            scope=_JSON_OBJECT_LIST.validate_python(scope_snapshot),
            reasoning_level=request.reasoning_level.value,
            locale=request.locale,
            time_zone=request.time_zone,
        )
    )
    start_event = encode_conversation_sse(
        ConversationStreamStartEvent(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            variant_index=turn_start.response.variant_index,
            generation_kind=generation_kind,
        )
    )

    if not turn_start.response_created and turn_start.response.status == "completed":
        persisted = turn_start.response
        snapshot = _latest_turn_snapshot(
            executor=executor,
            actor=current_user,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
        )

        async def replay_response() -> AsyncGenerator[str, None]:
            sequence = (
                max(
                    (entry.sequence for entry in persisted.trace.entries),
                    default=0,
                )
                + 1
                if persisted.trace is not None
                else 1
            )
            item_id = f"assistant:{request.turn_id}:{sequence}"
            yield start_event
            yield encode_conversation_sse(
                ConversationStreamAssistantItemStartEvent(
                    response_id=persisted.id,
                    item_id=item_id,
                    sequence=sequence,
                )
            )
            yield encode_conversation_sse(
                ConversationStreamAssistantItemDeltaEvent(
                    response_id=persisted.id,
                    item_id=item_id,
                    delta=persisted.content,
                )
            )
            yield encode_conversation_sse(
                ConversationStreamAssistantItemCompleteEvent(
                    response_id=persisted.id,
                    item=ConversationAssistantItem(
                        id=item_id,
                        sequence=sequence,
                        phase="final",
                        content=persisted.content,
                    ),
                )
            )
            if persisted.references is not None:
                yield encode_conversation_sse(
                    ConversationStreamReferencesEvent(
                        response_id=persisted.id,
                        references=persisted.references,
                    )
                )
            yield encode_conversation_sse(
                ConversationStreamResponseReadyEvent(turn=snapshot)
            )
            yield encode_conversation_sse(
                ConversationStreamCompleteEvent(
                    turn_id=request.turn_id,
                    response_id=persisted.id,
                )
            )

        return replay_response()
    if not turn_start.response_created:
        raise RuntimeError("Conversation response is already in progress")

    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=client_ip,
            feature="chat",
        )
        concurrency_lease = await acquire_concurrency(
            user_id=int(current_user.id),
            category="interactive",
        )
    except AILimitExceeded as exc:
        raise ai_limit_app_error(
            exc,
            exceeded_message="AI request limit exceeded",
        ) from None

    prior_history = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.history(
            actor=current_user,
            conversation_id=conversation_id,
            exclude_turn_id=request.turn_id,
        )
    )
    suggestion_task: asyncio.Task[tuple[str, str, str] | None] | None = None
    if not turn_start.suggestions:
        suggestion_task = asyncio.create_task(
            _generate_turn_suggestions(
                generator=suggestion_generator,
                seed=SuggestionSeed(
                    turn_id=request.turn_id,
                    user_query=request.user_query,
                    locale=request.locale,
                    recent_selected_turns=_recent_selected_turns(prior_history),
                    scope_titles=tuple(
                        str(item["title"])
                        for item in scope_snapshot
                        if item.get("title")
                    ),
                ),
                executor=executor,
                actor=current_user,
                conversation_id=conversation_id,
            ),
            name=f"conversation-suggestions:{request.turn_id}",
        )
    title_task: asyncio.Task[str | None] | None = None
    if turn_start.turn_created and conversation_scope.title_is_default:
        title_task = asyncio.create_task(
            _generate_initial_title(
                user_query=(
                    prior_history[0].content if prior_history else request.user_query
                ),
                conversation_id=conversation_id,
            ),
            name=f"conversation-title:{conversation_id}",
        )

    diagnostic_context: dict[str, object] = {
        "stage": "agent",
        "conversation_id": str(conversation_id),
        "turn_id": str(request.turn_id),
        "scope": conversation_scope.scope_type.value,
        "request": {
            "reasoning_level": request.reasoning_level.value,
            "locale": request.locale,
            "time_zone": request.time_zone,
            "permissions": sorted(
                permission.value for permission in conversation_scope.tool_permissions
            ),
        },
    }

    async def run_response_generator() -> AsyncGenerator[str, None]:
        yield start_event
        final_content = ""
        artifacts: list[dict[str, JsonValue]] = []
        references: ReferenceBundle | None = None
        trace: ConversationTrace | None = None
        started_at = datetime.now(timezone.utc)

        async for event in runtime.stream(
            request=request,
            actor=current_user,
            executor=executor,
            conversation_scope=conversation_scope,
            context_snapshot=context_snapshot,
            conversation_id=conversation_id,
            client_ip=client_ip,
            request_operation=operation,
            correlation_id=turn_start.correlation_id,
            user_operation_id=turn_start.turn_operation_id,
            mentioned_annotations=mentions.annotation_threads,
        ):
            if isinstance(event, ConversationAgentResult):
                trace = event.trace
                artifacts = event.artifacts
                continue
            if isinstance(event, ConversationStreamAssistantItemCompleteEvent):
                if event.item.phase == "final":
                    final_content = event.item.content
            elif isinstance(event, ConversationStreamReferencesEvent):
                references = ReferenceBundle.model_validate(event.references)
            yield encode_conversation_sse(event)

        if not final_content:
            raise RuntimeError("Conversation agent completed without a final answer")

        answer_finished_at = time.perf_counter()
        suggestion_finished_before_answer = bool(
            suggestion_task is None
            or (suggestion_task.done() and suggestion_task.result() is not None)
        )

        diagnostic_context["answer_char_count"] = len(final_content)
        diagnostic_context["activity_count"] = (
            sum(entry.kind == "activity" for entry in trace.entries) if trace else 0
        )
        answer_operation = operation_factory.resume(
            correlation_id=turn_start.correlation_id,
            causation_id=turn_start.turn_operation_id,
            initiated_by=OperationInitiator.AGENT,
            origin=operation.origin,
            credential=operation.credential,
        )
        executor.command(
            lambda capabilities: capabilities.conversation_chat_data.complete_turn(
                actor=current_user,
                operation=answer_operation,
                conversation_id=conversation_id,
                turn_id=request.turn_id,
                response_id=request.response_id,
                assistant_content=final_content,
                assistant_references=(
                    _JSON_OBJECT.validate_python(references.model_dump(mode="json"))
                    if references is not None
                    else None
                ),
                assistant_trace=trace,
                artifacts=artifacts,
            )
        )

        snapshot = _latest_turn_snapshot(
            executor=executor,
            actor=current_user,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
        )
        ready_at = time.perf_counter()
        yield encode_conversation_sse(
            ConversationStreamResponseReadyEvent(turn=snapshot)
        )

        suggestions_tail_ms: float | None = 0.0 if snapshot.suggestions else None
        sidecars = [task for task in (suggestion_task, title_task) if task is not None]
        if sidecars:
            done, pending = await asyncio.wait(
                sidecars,
                timeout=_SUGGESTION_TAIL_SECONDS,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if (
                suggestion_task is not None
                and suggestion_task in done
                and not snapshot.suggestions
            ):
                suggestions = suggestion_task.result()
                if suggestions is not None:
                    suggestions_tail_ms = (time.perf_counter() - ready_at) * 1_000
                    yield encode_conversation_sse(
                        ConversationStreamSuggestionsEvent(
                            turn_id=request.turn_id,
                            response_id=request.response_id,
                            suggestions=list(suggestions),
                        )
                    )
            if title_task is not None and title_task in done:
                title = title_task.result()
                if title is not None:
                    try:
                        await _apply_initial_title(
                            title=title,
                            executor=executor,
                            actor=current_user,
                            conversation_id=conversation_id,
                            operation=operation,
                            operation_factory=operation_factory,
                        )
                    except Exception:
                        logger.exception(
                            "conversation.title_persistence.failed",
                            extra={"conversation_id": str(conversation_id)},
                        )

        scope_items = scope_snapshot or []
        track_event(
            "did_chat_message",
            properties={
                "has_turn_context": bool(request.contexts),
                "has_references": references is not None,
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - started_at).total_seconds(),
                "answer_to_ready_ms": (ready_at - answer_finished_at) * 1_000,
                "suggestions_ready_before_answer": suggestion_finished_before_answer,
                "suggestions_tail_ms": suggestions_tail_ms,
                "type": conversation_scope.scope_type.value,
                "project_id": str(project_id) if project_id is not None else None,
                "num_context_papers": sum(
                    item.get("kind") == "paper" for item in scope_items
                ),
                "num_context_projects": sum(
                    item.get("kind") == "project" for item in scope_items
                ),
                "num_mentioned_annotations": sum(
                    item.get("kind") == "annotation_thread" for item in scope_items
                ),
                "uses_library_context": (
                    conversation_scope.paper_context.kind == "library"
                ),
            },
            user_id=str(current_user.id),
        )
        yield encode_conversation_sse(
            ConversationStreamCompleteEvent(
                turn_id=request.turn_id,
                response_id=request.response_id,
            )
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(user_id=int(current_user.id), feature="chat"):
                async for event in stream_with_stable_error(
                    run_response_generator(),
                    event_name="conversation_chat_message_error",
                    user_id=current_user.id,
                    properties={
                        "type": conversation_scope.scope_type.value,
                        "conversation_id": str(conversation_id),
                    },
                    diagnostic_recorder=diagnostic_recorder,
                    diagnostic_context=diagnostic_context,
                    response_id=request.response_id,
                ):
                    yield event
        except asyncio.CancelledError:
            executor.command(
                lambda capabilities: (
                    capabilities.conversation_chat_data.finish_response(
                        actor=current_user,
                        conversation_id=conversation_id,
                        response_id=request.response_id,
                        status="cancelled",
                    )
                )
            )
            raise
        except Exception:
            executor.command(
                lambda capabilities: (
                    capabilities.conversation_chat_data.finish_response(
                        actor=current_user,
                        conversation_id=conversation_id,
                        response_id=request.response_id,
                        status="failed",
                    )
                )
            )
            raise
        finally:
            for task in (suggestion_task, title_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (suggestion_task, title_task) if task is not None),
                return_exceptions=True,
            )
            await release_concurrency(concurrency_lease)

    return response_generator()


class DefaultConversationChatGateway:
    """Runs every Conversation scope through the shared agent runtime."""

    def __init__(
        self,
        executor: ApplicationExecutor[ApplicationCapabilities],
        runtime: ScholensConversationAgent,
        operation_factory: OperationContextFactory,
        diagnostic_recorder: DiagnosticSnapshotRecorder,
        suggestion_generator: ConversationSuggestionGenerator,
    ) -> None:
        self._executor = executor
        self._runtime = runtime
        self._operation_factory = operation_factory
        self._diagnostic_recorder = diagnostic_recorder
        self._suggestion_generator = suggestion_generator

    async def stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry"] = "initial",
    ) -> AsyncGenerator[str, None]:
        return await stream_conversation_agent(
            request,
            conversation_id=conversation_id,
            client_ip=client_ip,
            executor=self._executor,
            current_user=actor,
            runtime=self._runtime,
            operation=operation,
            operation_factory=self._operation_factory,
            suggestion_generator=self._suggestion_generator,
            generation_kind=generation_kind,
            diagnostic_recorder=self._diagnostic_recorder,
        )

    async def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        client_ip: str,
    ) -> AsyncGenerator[str, None]:
        request = self._executor.query(
            lambda capabilities: capabilities.conversation_chat_data.retry_request(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
            )
        )
        return await self.stream(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind="retry",
        )
