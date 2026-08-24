"""Public Conversation streaming adapter for the single Scholens agent."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Literal, Protocol, TypeVar, cast

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.ai_limits import (
    AIConcurrencyLease,
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
    fallback_conversation_title,
    initial_conversation_title_generator,
)
from app.llm.follow_up_suggestions import SuggestionSeed
from app.llm.token_credits import llm_usage_context
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationTurnBranchCreateRequest,
    ConversationTurnCreateRequest,
    ConversationStreamAssistantCandidateDeltaEvent,
    ConversationStreamAssistantCandidateResetEvent,
    ConversationStreamAssistantCandidateStartEvent,
    ConversationStreamAssistantItemCompleteEvent,
    ConversationStreamCancelledEvent,
    ConversationStreamCompleteEvent,
    ConversationStreamErrorEvent,
    ConversationStreamReferencesEvent,
    ConversationStreamResponseReadyEvent,
    ConversationStreamStartEvent,
    ConversationStreamSuggestionsEvent,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationGenerationAccepted,
    ConversationGenerationCancellation,
    ConversationResponseVariantResponse,
    ConversationTurnResponse,
)
from app.modules.conversations.application.chat import (
    ChatHistoryMessage,
    ConversationChatScope,
    ConversationContextSnapshot,
    ConversationGenerationPreparation,
    ConversationTurnStart,
    MentionScope,
)
from app.modules.jobs.application.jobs import EnqueueJobCommand
from app.modules.jobs.infrastructure.dispatcher_wakeup import JobDispatcherWakeup
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_keepalive,
    stream_with_stable_error,
)
from app.modules.conversations.infrastructure.event_store import ConversationEventStore
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    SelectedPaperCollection,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import ConversationScopeType, JobOperation
from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from scholens_job_contracts import JobQueue
from scholens_observability import DiagnosticSnapshotRecorder, record_histogram

logger = logging.getLogger(__name__)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, JsonValue]])
_SUGGESTION_TAIL_SECONDS = 2.0
_T = TypeVar("_T")


async def _resolve_thread_command(
    command: Callable[[], _T],
) -> tuple[_T, asyncio.CancelledError | None]:
    """Wait for an offloaded transaction's real outcome before propagating cancel."""

    task = asyncio.create_task(asyncio.to_thread(command))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(task), cancellation
        except asyncio.CancelledError as error:
            if task.done():
                if cancellation is None:
                    cancellation = error
                if task.cancelled():
                    raise cancellation
                try:
                    return task.result(), cancellation
                except BaseException:
                    raise cancellation
            if cancellation is None:
                cancellation = error
        except BaseException:
            if cancellation is not None:
                raise cancellation
            raise


def _start_paper_collection(request: ConversationCreateRequest) -> PaperCollection:
    context = request.paper_context
    if context is None:
        if request.scope_type is ConversationScopeType.GLOBAL:
            return LibraryPaperCollection()
        assert request.scope_id is not None
        if request.scope_type is ConversationScopeType.PROJECT:
            return SelectedPaperCollection(project_ids=[request.scope_id])
        return SelectedPaperCollection(document_ids=[request.scope_id])
    if context.kind == "library":
        return LibraryPaperCollection()
    project_ids = set(context.project_ids)
    document_ids = set(context.document_ids)
    if request.scope_type is ConversationScopeType.PROJECT:
        assert request.scope_id is not None
        project_ids.add(request.scope_id)
    elif request.scope_type is ConversationScopeType.PAPER:
        assert request.scope_id is not None
        document_ids.add(request.scope_id)
    return SelectedPaperCollection(
        project_ids=sorted(project_ids, key=str),
        document_ids=sorted(document_ids, key=str),
    )


def _generation_payload(
    *,
    conversation_id: uuid.UUID,
    request: ConversationTurnCreateRequest,
    generation_kind: Literal["initial", "retry", "branch"],
) -> dict[str, JsonValue]:
    return {
        "conversation_id": str(conversation_id),
        "turn_id": str(request.turn_id),
        "response_id": str(request.response_id),
        "generation_kind": generation_kind,
    }


def _is_assistant_candidate_frame(frame: str) -> bool:
    return any(
        line.startswith("event: assistant_candidate_") for line in frame.splitlines()
    )


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


def _generation_snapshot(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    actor: Actor,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    response_id: uuid.UUID,
) -> tuple[ConversationTurnResponse, ConversationResponseVariantResponse]:
    page = executor.query(
        lambda capabilities: capabilities.conversations.turns(
            actor=actor,
            conversation_id=conversation_id,
            cursor=None,
            limit=100,
        )
    )
    turn = next((item for item in page.items if item.id == turn_id), None)
    response = (
        next((item for item in turn.responses if item.id == response_id), None)
        if turn is not None
        else None
    )
    if turn is None or response is None:
        raise AppError(
            code="conversation_response_not_found",
            message="Conversation response not found",
            kind=FailureKind.NOT_FOUND,
        )
    return turn, response


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
    preparation: ConversationGenerationPreparation,
    *,
    conversation_id: uuid.UUID,
    client_ip: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    current_user: Actor,
    runtime: ScholensConversationAgent,
    operation: OperationContext,
    operation_factory: OperationContextFactory,
    suggestion_generator: ConversationSuggestionGenerator,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
    include_assistant_candidates: bool = False,
) -> AsyncGenerator[str, None]:
    """Resume one accepted durable generation and expose its product event stream."""
    request = preparation.request
    turn_start = preparation.turn_start

    def prepare_runtime(
        capabilities: ApplicationCapabilities,
    ) -> tuple[ConversationChatScope, MentionScope, ConversationContextSnapshot]:
        conversation_scope = capabilities.conversation_chat_data.prepare(
            actor=current_user,
            conversation_id=conversation_id,
            paper_context_snapshot=preparation.paper_context,
        )
        return (
            conversation_scope,
            capabilities.conversation_chat_data.mentions(
                actor=current_user,
                request=request,
            ),
            capabilities.conversation_chat_data.context(
                actor=current_user,
                scope=conversation_scope,
            ),
        )

    conversation_scope, mentions, context_snapshot = await asyncio.to_thread(
        executor.query,
        prepare_runtime,
    )
    project_id = conversation_scope.project_id

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

    concurrency_lease = AIConcurrencyLease(
        key=f"scholens:concurrency:interactive:{current_user.id}",
        member=str(request.response_id),
    )

    response_started_at = time.perf_counter()

    def elapsed_ms() -> int:
        return max(0, round((time.perf_counter() - response_started_at) * 1_000))

    start_event = encode_conversation_sse(
        ConversationStreamStartEvent(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            variant_index=turn_start.response.variant_index,
            generation_kind=turn_start.generation_kind,
        )
    )
    suggestion_task: asyncio.Task[tuple[str, str, str] | None] | None = None
    title_task: asyncio.Task[str | None] | None = None
    title_seed: str | None = None

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

    async def produce_response() -> AsyncGenerator[str, None]:
        nonlocal suggestion_task, title_seed, title_task

        history = await asyncio.to_thread(
            executor.query,
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=conversation_id,
                before_turn_id=request.turn_id,
            ),
        )

        def start_sidecars() -> None:
            nonlocal suggestion_task, title_seed, title_task
            if turn_start.suggestions and not conversation_scope.title_is_default:
                return
            if not turn_start.suggestions:
                suggestion_task = asyncio.create_task(
                    _generate_turn_suggestions(
                        generator=suggestion_generator,
                        seed=SuggestionSeed(
                            turn_id=request.turn_id,
                            user_query=request.user_query,
                            locale=request.locale,
                            recent_selected_turns=_recent_selected_turns(history),
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
            if conversation_scope.title_is_default:
                title_seed = history[0].content if history else request.user_query
                title_task = asyncio.create_task(
                    _generate_initial_title(
                        user_query=title_seed,
                        conversation_id=conversation_id,
                    ),
                    name=f"conversation-title:{conversation_id}",
                )

        final_content = ""
        artifacts: list[dict[str, JsonValue]] = []
        references: ReferenceBundle | None = None
        trace: ConversationTrace | None = None
        sidecars_started = False
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
            history=history,
        ):
            if isinstance(event, ConversationAgentResult):
                trace = event.trace
                artifacts = event.artifacts
                continue
            if (
                isinstance(
                    event,
                    (
                        ConversationStreamAssistantCandidateStartEvent,
                        ConversationStreamAssistantCandidateDeltaEvent,
                        ConversationStreamAssistantCandidateResetEvent,
                    ),
                )
                and not include_assistant_candidates
            ):
                continue
            if isinstance(event, ConversationStreamAssistantItemCompleteEvent):
                if event.item.phase == "final":
                    final_content = event.item.content
            elif isinstance(event, ConversationStreamReferencesEvent):
                references = ReferenceBundle.model_validate(event.references)
            yield encode_conversation_sse(event)
            if not sidecars_started:
                # The keepalive pump can prefetch synchronously. Hand control back
                # so this first public frame can leave the process before sidecar
                # task scheduling or provider calls begin.
                await asyncio.sleep(0)
                start_sidecars()
                sidecars_started = True

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
        completion = executor.command(
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
                duration_ms=elapsed_ms(),
            )
        )
        if completion.response.status == "cancelled":
            raise asyncio.CancelledError
        if completion.response.status != "completed":
            raise RuntimeError("Conversation response did not complete")

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
            if title_task is not None and title_seed is not None:
                title: str | None = None
                if title_task in done and not title_task.cancelled():
                    try:
                        title = title_task.result()
                    except Exception:
                        logger.exception(
                            "conversation.title_generation.failed",
                            extra={"conversation_id": str(conversation_id)},
                        )
                title = title or fallback_conversation_title(title_seed)
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
                "time_taken": elapsed_ms() / 1_000,
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

    async def run_response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(user_id=int(current_user.id), feature="chat"):
                async for event in produce_response():
                    yield event
        except asyncio.CancelledError:
            executor.command(
                lambda capabilities: (
                    capabilities.conversation_chat_data.finish_response(
                        actor=current_user,
                        conversation_id=conversation_id,
                        response_id=request.response_id,
                        status="cancelled",
                        duration_ms=elapsed_ms(),
                    )
                )
            )
            raise
        except Exception:
            raise

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            yield start_event
            async for event in stream_with_stable_error(
                stream_with_keepalive(run_response_generator()),
                event_name="conversation_chat_message_error",
                user_id=current_user.id,
                properties={
                    "type": conversation_scope.scope_type.value,
                    "conversation_id": str(conversation_id),
                },
                diagnostic_recorder=diagnostic_recorder,
                diagnostic_context=diagnostic_context,
                response_id=request.response_id,
                failure_sink=lambda failure: executor.command(
                    lambda capabilities: (
                        capabilities.conversation_chat_data.finish_response(
                            actor=current_user,
                            conversation_id=conversation_id,
                            response_id=request.response_id,
                            status="failed",
                            duration_ms=elapsed_ms(),
                            failure=failure,
                        )
                    )
                ),
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
                        duration_ms=elapsed_ms(),
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
                        duration_ms=elapsed_ms(),
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
        event_store_url: str | None = None,
        dispatcher_wakeup: JobDispatcherWakeup | None = None,
    ) -> None:
        self._executor = executor
        self._runtime = runtime
        self._operation_factory = operation_factory
        self._diagnostic_recorder = diagnostic_recorder
        self._suggestion_generator = suggestion_generator
        self._event_store_url = event_store_url
        self._dispatcher_wakeup = dispatcher_wakeup

    @staticmethod
    async def _acquire_acceptance_limits(
        *,
        actor: Actor,
        response_id: uuid.UUID,
        client_ip: str,
    ) -> bool:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=client_ip,
                feature="chat",
                operation_id=str(response_id),
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None
        try:
            lease = await acquire_concurrency(
                user_id=actor.id,
                category="interactive",
                operation_id=str(response_id),
            )
        except BaseException as error:
            # A deterministic response ID may already be the valid lease for an
            # accepted replay. When Redis makes the acquire outcome ambiguous,
            # removing it could drop that running generation's protection. Any
            # newly inserted ambiguous member remains bounded by Redis TTL.
            if isinstance(error, AILimitExceeded):
                raise ai_limit_app_error(
                    error,
                    exceeded_message="AI request limit exceeded",
                ) from None
            raise
        return lease.created

    @staticmethod
    async def _release_acceptance_limit(
        *,
        actor: Actor,
        response_id: uuid.UUID,
    ) -> None:
        await release_concurrency(
            AIConcurrencyLease(
                key=f"scholens:concurrency:interactive:{actor.id}",
                member=str(response_id),
            )
        )

    @staticmethod
    def _persist_generation(
        capabilities: ApplicationCapabilities,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        conversation_scope: ConversationChatScope,
        generation_kind: Literal["initial", "retry", "branch"],
        branch_from_turn_id: uuid.UUID | None,
    ) -> ConversationTurnStart:
        serialized_contexts = _JSON_OBJECT_LIST.validate_python(
            [context.model_dump(mode="json") for context in request.contexts]
        )
        paper_context = _JSON_OBJECT.validate_python(
            conversation_scope.paper_context.model_dump(mode="json")
        )
        turn_start = capabilities.conversation_chat_data.start_turn(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            generation_kind=generation_kind,
            user_content=request.user_query,
            contexts=serialized_contexts,
            paper_context=paper_context,
            reasoning_level=request.reasoning_level.value,
            locale=request.locale,
            time_zone=request.time_zone,
            branch_from_turn_id=branch_from_turn_id,
        )
        payload = _generation_payload(
            conversation_id=conversation_id,
            request=request,
            generation_kind=generation_kind,
        )
        enqueued = capabilities.job_commands.enqueue(
            command=EnqueueJobCommand(
                job_id=request.response_id,
                operation=JobOperation.CONVERSATION_GENERATE,
                requested_by_id=actor.id,
                correlation_id=turn_start.correlation_id,
                origin_operation_id=turn_start.turn_operation_id,
                idempotency_key=f"conversation-response:{request.response_id}",
                payload=payload,
                task_name=(
                    "app.bootstrap.adapters.conversation_worker."
                    "generate_conversation_response"
                ),
                queue=JobQueue.CONVERSATION,
                project_id=conversation_scope.project_id,
                document_id=conversation_scope.document_id,
            )
        )
        if not enqueued.created and (
            turn_start.response_created
            or enqueued.job.id != request.response_id
            or enqueued.payload != payload
            or (
                turn_start.response.status == "running"
                and enqueued.job.status not in {"pending", "running"}
            )
        ):
            raise AppError(
                code="conversation_generation_conflict",
                message="This response identifier already belongs to another generation",
                kind=FailureKind.CONFLICT,
            )
        return turn_start

    @staticmethod
    def _accepted_generation(
        *,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        turn_start: ConversationTurnStart,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> ConversationGenerationAccepted:
        return ConversationGenerationAccepted(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            variant_index=turn_start.response.variant_index,
            generation_kind=generation_kind,
        )

    @staticmethod
    def _resume_start(
        capabilities: ApplicationCapabilities,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        conversation: ConversationCreateRequest,
        request: ConversationTurnCreateRequest,
        paper_context: PaperCollection,
    ) -> ConversationTurnStart:
        try:
            replay = capabilities.conversation_chat_data.resume_generation(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=request.turn_id,
                response_id=request.response_id,
                generation_kind="initial",
            )
        except AppError as response_error:
            if response_error.code != "conversation_response_not_found":
                raise
            raise AppError(
                code="conversation_start_conflict",
                message="This conversation identifier already belongs to another start",
                kind=FailureKind.CONFLICT,
            ) from None
        if replay.request != request or replay.paper_context != paper_context:
            raise AppError(
                code="conversation_start_conflict",
                message=(
                    "This conversation start was already used with different "
                    "turn content"
                ),
                kind=FailureKind.CONFLICT,
            )
        persisted_job = capabilities.job_commands.find_by_idempotency_key(
            key=f"conversation-response:{request.response_id}"
        )
        expected_project_id = (
            conversation.scope_id
            if conversation.scope_type is ConversationScopeType.PROJECT
            else None
        )
        expected_document_id = (
            conversation.scope_id
            if conversation.scope_type is ConversationScopeType.PAPER
            else None
        )
        if persisted_job is None or (
            persisted_job.project_id,
            persisted_job.document_id,
        ) != (expected_project_id, expected_document_id):
            raise AppError(
                code="conversation_start_conflict",
                message="This conversation start used a different original scope",
                kind=FailureKind.CONFLICT,
            )
        return replay.turn_start

    def _notify_dispatcher(self) -> None:
        if self._dispatcher_wakeup is not None:
            self._dispatcher_wakeup.notify()

    async def _durable_generation_matches(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        generation_kind: Literal["initial", "retry", "branch"],
        active_only: bool,
    ) -> bool:
        def matches(capabilities: ApplicationCapabilities) -> bool:
            job = capabilities.job_commands.find_by_idempotency_key(
                key=f"conversation-response:{request.response_id}"
            )
            if job is None or (
                active_only and job.status not in {"pending", "running"}
            ):
                return False
            try:
                persisted = capabilities.conversation_chat_data.resume_generation(
                    actor=actor,
                    conversation_id=conversation_id,
                    turn_id=request.turn_id,
                    response_id=request.response_id,
                    generation_kind=generation_kind,
                )
            except AppError:
                return False
            return persisted.request == request and (
                not active_only or persisted.turn_start.response.status == "running"
            )

        return await asyncio.to_thread(
            self._executor.query,
            matches,
        )

    async def _accept_persisted_generation(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry", "branch"],
        persist: Callable[[], ConversationTurnStart],
        started_at: float,
        map_error: Callable[[BaseException], AppError | None] | None = None,
    ) -> ConversationGenerationAccepted:
        metric_status = "failure"
        try:
            limits_acquired = False
            acquired_new_limit = False
            try:
                acquired_new_limit = await self._acquire_acceptance_limits(
                    actor=actor,
                    response_id=request.response_id,
                    client_ip=client_ip,
                )
                limits_acquired = True
            except AppError as limit_error:
                if limit_error.kind not in {
                    FailureKind.RATE_LIMITED,
                    FailureKind.UNAVAILABLE,
                } or not await self._durable_generation_matches(
                    actor=actor,
                    conversation_id=conversation_id,
                    request=request,
                    generation_kind=generation_kind,
                    active_only=False,
                ):
                    raise

            transaction_started = time.perf_counter()
            transaction_status = "failure"
            try:
                turn_start, cancellation = await _resolve_thread_command(persist)
                transaction_status = "success"
            except BaseException as error:
                if limits_acquired and acquired_new_limit:
                    try:
                        committed_generation_exists = (
                            await self._durable_generation_matches(
                                actor=actor,
                                conversation_id=conversation_id,
                                request=request,
                                generation_kind=generation_kind,
                                active_only=True,
                            )
                        )
                    except Exception:
                        # Preserve a possibly committed generation's lease when the
                        # ownership check itself is unavailable. Redis TTL bounds a
                        # lease that turns out to have been newly orphaned.
                        committed_generation_exists = True
                        logger.warning(
                            "conversation.acceptance_cleanup.deferred",
                            exc_info=True,
                        )
                    if not committed_generation_exists:
                        await self._release_acceptance_limit(
                            actor=actor,
                            response_id=request.response_id,
                        )
                mapped = map_error(error) if map_error is not None else None
                if mapped is not None:
                    raise mapped from None
                raise
            finally:
                record_histogram(
                    "scholens.conversation.accept.transaction_duration",
                    (time.perf_counter() - transaction_started) * 1000,
                    attributes={
                        "status": transaction_status,
                        "generation_kind": generation_kind,
                    },
                )

            self._notify_dispatcher()
            if (
                limits_acquired
                and not turn_start.response_created
                and turn_start.response.status != "running"
            ):
                await self._release_acceptance_limit(
                    actor=actor,
                    response_id=request.response_id,
                )
            metric_status = "accepted" if turn_start.response_created else "idempotent"
            accepted = self._accepted_generation(
                conversation_id=conversation_id,
                request=request,
                turn_start=turn_start,
                generation_kind=generation_kind,
            )
            if cancellation is not None:
                raise cancellation
            return accepted
        finally:
            record_histogram(
                "scholens.conversation.accept.total_duration",
                (time.perf_counter() - started_at) * 1000,
                attributes={
                    "status": metric_status,
                    "generation_kind": generation_kind,
                },
            )

    async def accept(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry", "branch"] = "initial",
        branch_from_turn_id: uuid.UUID | None = None,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationGenerationAccepted:
        started = time.perf_counter()
        try:
            conversation_scope = await asyncio.to_thread(
                self._executor.query,
                lambda capabilities: capabilities.conversation_chat_data.prepare(
                    actor=actor,
                    conversation_id=conversation_id,
                    paper_context_snapshot=paper_context_snapshot,
                ),
            )
        except BaseException:
            record_histogram(
                "scholens.conversation.accept.total_duration",
                (time.perf_counter() - started) * 1000,
                attributes={
                    "status": "failure",
                    "generation_kind": generation_kind,
                },
            )
            raise

        return await self._accept_persisted_generation(
            actor=actor,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind=generation_kind,
            persist=lambda: self._executor.command(
                lambda capabilities: self._persist_generation(
                    capabilities,
                    actor=actor,
                    operation=operation,
                    conversation_id=conversation_id,
                    request=request,
                    conversation_scope=conversation_scope,
                    generation_kind=generation_kind,
                    branch_from_turn_id=branch_from_turn_id,
                )
            ),
            started_at=started,
        )

    async def accept_start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        conversation: ConversationCreateRequest,
        request: ConversationTurnCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        started = time.perf_counter()
        generation_kind: Literal["initial"] = "initial"

        def persist(capabilities: ApplicationCapabilities) -> ConversationTurnStart:
            creation = capabilities.conversations.create_with_id(
                actor=actor,
                operation=operation,
                conversation_id=conversation_id,
                request=conversation,
            )
            expected_paper_context = _start_paper_collection(conversation)
            if not creation.changed:
                return self._resume_start(
                    capabilities,
                    actor=actor,
                    conversation_id=conversation_id,
                    conversation=conversation,
                    request=request,
                    paper_context=expected_paper_context,
                )
            conversation_scope = capabilities.conversation_chat_data.prepare(
                actor=actor,
                conversation_id=conversation_id,
            )
            if conversation_scope.paper_context != expected_paper_context:
                raise AppError(
                    code="conversation_start_conflict",
                    message=(
                        "The existing conversation context does not match this new start"
                    ),
                    kind=FailureKind.CONFLICT,
                )
            return self._persist_generation(
                capabilities,
                actor=actor,
                operation=operation,
                conversation_id=conversation_id,
                request=request,
                conversation_scope=conversation_scope,
                generation_kind=generation_kind,
                branch_from_turn_id=None,
            )

        def map_start_conflict(error: BaseException) -> AppError | None:
            if isinstance(error, IntegrityError) or (
                isinstance(error, AppError)
                and error.kind is FailureKind.CONFLICT
                and error.code.startswith("conversation_")
            ):
                return AppError(
                    code="conversation_start_conflict",
                    message=(
                        "The conversation, turn, or response identifier was already "
                        "used differently"
                    ),
                    kind=FailureKind.CONFLICT,
                )
            return None

        return await self._accept_persisted_generation(
            actor=actor,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind=generation_kind,
            persist=lambda: self._executor.command(persist),
            started_at=started,
            map_error=map_start_conflict,
        )

    async def resume(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        generation_kind: Literal["initial", "retry", "branch"],
    ) -> AsyncGenerator[str, None]:
        preparation = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.conversation_chat_data.resume_generation(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
                generation_kind=generation_kind,
            ),
        )
        return await stream_conversation_agent(
            preparation,
            conversation_id=conversation_id,
            client_ip="127.0.0.1",
            executor=self._executor,
            current_user=actor,
            runtime=self._runtime,
            operation=operation,
            operation_factory=self._operation_factory,
            suggestion_generator=self._suggestion_generator,
            diagnostic_recorder=self._diagnostic_recorder,
            include_assistant_candidates=True,
        )

    async def accept_retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        request = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.conversation_chat_data.retry_request(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
            ),
        )
        return await self.accept(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind="retry",
        )

    async def accept_branch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        source_turn_id: uuid.UUID,
        request: ConversationTurnBranchCreateRequest,
        client_ip: str,
    ) -> ConversationGenerationAccepted:
        preparation = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.conversation_chat_data.branch_request(
                actor=actor,
                conversation_id=conversation_id,
                source_turn_id=source_turn_id,
                request=request,
            ),
        )
        return await self.accept(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=preparation.request,
            client_ip=client_ip,
            generation_kind="branch",
            branch_from_turn_id=source_turn_id,
            paper_context_snapshot=preparation.paper_context,
        )

    async def subscribe(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        last_event_id: str | None,
        include_assistant_candidates: bool = False,
    ) -> AsyncIterator[str]:
        await asyncio.to_thread(
            _generation_snapshot,
            executor=self._executor,
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )

        async def events() -> AsyncIterator[str]:
            cursor = last_event_id
            store = ConversationEventStore(self._event_store_url)
            while True:
                async for frame in store.subscribe(
                    response_id=response_id,
                    after=cursor,
                ):
                    if frame is not None:
                        first_line = frame.partition("\n")[0]
                        if first_line.startswith("id: "):
                            cursor = first_line.removeprefix("id: ")
                        if (
                            not include_assistant_candidates
                            and _is_assistant_candidate_frame(frame)
                        ):
                            continue
                        yield frame
                        if any(
                            terminal in frame
                            for terminal in (
                                "event: complete\n",
                                "event: cancelled\n",
                                "event: error\n",
                            )
                        ):
                            return
                        continue
                    turn, response = await asyncio.to_thread(
                        _generation_snapshot,
                        executor=self._executor,
                        actor=actor,
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        response_id=response_id,
                    )
                    if response.status == "completed":
                        yield encode_conversation_sse(
                            ConversationStreamResponseReadyEvent(turn=turn)
                        )
                        yield encode_conversation_sse(
                            ConversationStreamCompleteEvent(
                                turn_id=turn_id,
                                response_id=response_id,
                            )
                        )
                        return
                    if response.status == "failed":
                        failure = response.failure
                        yield encode_conversation_sse(
                            ConversationStreamErrorEvent(
                                response_id=response_id,
                                error=(
                                    failure.model_dump(mode="json")
                                    if failure is not None
                                    else {
                                        "code": "conversation_generation_failed",
                                        "kind": FailureKind.DEPENDENCY_FAILURE.value,
                                        "retryable": True,
                                    }
                                ),
                            )
                        )
                        return
                    if response.status == "cancelled":
                        yield encode_conversation_sse(
                            ConversationStreamCancelledEvent(
                                turn_id=turn_id,
                                response_id=response_id,
                            )
                        )
                        return
                    yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        return events()

    async def cancel(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
    ) -> ConversationGenerationCancellation:
        def cancel(
            capabilities: ApplicationCapabilities,
        ) -> ConversationGenerationCancellation:
            response = capabilities.conversation_chat_data.cancel_generation(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
            )
            if response.status == "cancelled":
                capabilities.job_commands.cancel(
                    requested_by_id=actor.id,
                    job_id=response_id,
                )
            return ConversationGenerationCancellation(
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
                status=cast(
                    Literal["completed", "failed", "cancelled"], response.status
                ),
            )

        result, cancellation = await _resolve_thread_command(
            lambda: self._executor.command(cancel)
        )
        if result.status == "cancelled":
            await asyncio.gather(
                ConversationEventStore(self._event_store_url).append_terminal(
                    response_id=response_id,
                    frame=encode_conversation_sse(
                        ConversationStreamCancelledEvent(
                            turn_id=turn_id,
                            response_id=response_id,
                        )
                    ),
                ),
                release_concurrency(
                    AIConcurrencyLease(
                        key=f"scholens:concurrency:interactive:{actor.id}",
                        member=str(response_id),
                    )
                ),
            )
        if cancellation is not None:
            raise cancellation
        return result
