from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.llm.conversation_agent import (
    ConversationAgentResult,
    ConversationAgentStreamEvent,
    ScholensConversationAgent,
    _unsafe_candidate_suffix_length,
)
from app.modules.conversations.application.chat import (
    ChatPaperSnapshot,
    ConversationChatScope,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationTurnCreateRequest,
    ConversationStreamActivityEvent,
    ConversationStreamAssistantCandidateDeltaEvent,
    ConversationStreamAssistantCandidateStartEvent,
    ConversationStreamAssistantItemCompleteEvent,
    ConversationStreamAssistantItemDeltaEvent,
    ConversationStreamReferencesEvent,
)
from app.modules.conversations.application.contracts.trace import (
    ConversationActivity,
    ConversationTrace,
)
from app.modules.conversations.application.contracts.answer_packet import (
    AnswerCoverage,
    AnswerPacket,
    ReferenceBundle,
)
from app.llm.grounded_answer import GroundedAnswerMetrics
from app.modules.integrations.connectors.infrastructure.mcp import (
    ConnectorToolIssue,
    ResolvedConnectorToolSet,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    SelectedPaperCollection,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from app.tooling import (
    DocumentSourceCandidate,
    ToolCatalog,
    ToolDefinition,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.workspace import CONVERSATION_TOOL_PROFILE
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, RetryPromptPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel


class SearchInput(BaseModel):
    query: str


def _text_answer(answer: str) -> str:
    return answer


def _grounded_text_answer(
    answer: str,
    info: AgentInfo,
) -> str:
    nonce_match = re.search(
        r"SCHOLENS_CITE:([0-9a-f]+):1",
        info.instructions or "",
    )
    assert nonce_match is not None
    return _text_answer(f"{answer}[[SCHOLENS_CITE:{nonce_match.group(1)}:1]]")


def _unused_handler(*_args: object, **_kwargs: object) -> ToolOutcome:
    raise AssertionError("the runtime must use ToolDispatcher")


def test_rejected_only_sources_are_reported_as_unavailable() -> None:
    packet = AnswerPacket(
        context={},
        materials=[],
        actions=[],
        sources=[],
        coverage=AnswerCoverage(
            observations_total=1,
            observations_processed=1,
            truncated_observations=0,
            truncated_materials=0,
            truncated_sources=0,
            truncated_actions=0,
            rejected_sources=1,
            failed_observations=0,
        ),
    )
    summary = ScholensConversationAgent._citation_summary(
        packet=packet,
        references=None,
        metrics=GroundedAnswerMetrics(
            annotations_emitted=0,
            invalid_source_keys=0,
            protocol_errors=0,
        ),
    )

    assert summary.status == "unavailable"
    assert summary.source_count == 0
    assert summary.rejected_source_count == 1


def _catalog(*, allow_repeated_calls: bool = False) -> ToolCatalog[Any]:
    return ToolCatalog(
        [
            ToolDefinition(
                name="search_saved_papers",
                description="Search the authorized paper collection.",
                input_model=SearchInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=_unused_handler,
                activity_subject_field="query",
                allow_repeated_calls=allow_repeated_calls,
            )
        ],
        [
            ToolProfile(
                name=CONVERSATION_TOOL_PROFILE,
                tool_names=frozenset({"search_saved_papers"}),
            )
        ],
    )


class _ChatData:
    @staticmethod
    def history(**_kwargs: object) -> list[object]:
        return []


class _Capabilities:
    conversation_chat_data = _ChatData()


class _Executor:
    def query(self, operation: Any) -> Any:
        return operation(_Capabilities())


class _ConnectorTools:
    def __init__(self, connector_set: ResolvedConnectorToolSet | None = None) -> None:
        self._connector_set = connector_set or ResolvedConnectorToolSet()

    async def resolve(self, **_kwargs: object) -> ResolvedConnectorToolSet:
        return self._connector_set


class _Dispatcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.document_id = uuid4()

    async def dispatch(
        self, *, name: str, raw_arguments: dict[str, Any], **_kwargs: Any
    ) -> ToolOutcome:
        self.calls.append((name, raw_arguments))
        if self.fail:
            raise AppError(
                code="search_temporarily_unavailable",
                message="Search is unavailable",
                kind=FailureKind.DEPENDENCY_FAILURE,
            )
        return ToolOutcome(
            payload={"results": [{"title": "A grounded paper"}]},
            sources=(
                DocumentSourceCandidate(
                    document_id=self.document_id,
                    title="A grounded paper",
                    excerpt="Validated evidence about chain-of-thought compression.",
                ),
            ),
        )


class _InvalidArgumentsThenSuccessDispatcher(_Dispatcher):
    async def dispatch(
        self, *, name: str, raw_arguments: dict[str, Any], **kwargs: Any
    ) -> ToolOutcome:
        if not self.calls:
            self.calls.append((name, raw_arguments))
            raise AppError(
                code="tool_arguments_invalid",
                message="Tool arguments are invalid",
                kind=FailureKind.INVALID_ARGUMENT,
                details={
                    "errors": [
                        {
                            "type": "dict_type",
                            "loc": ("scope",),
                            "msg": "Input should be a valid dictionary",
                        }
                    ]
                },
            )
        return await super().dispatch(
            name=name,
            raw_arguments=raw_arguments,
            **kwargs,
        )


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 8, 5, 16, 30, tzinfo=timezone.utc)


def _request_operation(conversation_id: UUID, turn_id: UUID) -> Any:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=conversation_id,
            turn_id=turn_id,
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _scope() -> ConversationChatScope:
    return ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset({WorkspacePermission.READ}),
        title_is_default=True,
    )


def _snapshot(dispatcher: _Dispatcher) -> ConversationContextSnapshot:
    return ConversationContextSnapshot(
        papers=[
            ChatPaperSnapshot(
                document_id=dispatcher.document_id,
                title="A grounded paper",
                abstract="Validated abstract.",
                raw_content="Validated evidence about chain-of-thought compression.",
                keywords=None,
                authors=["Researcher"],
                publish_date=None,
            )
        ],
        projects=[],
        available_document_count=1,
    )


async def _events(
    *,
    model: Any,
    dispatcher: _Dispatcher,
    query: str,
    locale: str = "zh-CN",
    time_zone: str = "Asia/Shanghai",
    scope: ConversationChatScope | None = None,
    connector_set: ResolvedConnectorToolSet | None = None,
    allow_repeated_calls: bool = False,
) -> list[ConversationAgentStreamEvent]:
    runtime = ScholensConversationAgent(
        catalog=_catalog(allow_repeated_calls=allow_repeated_calls),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        connector_tools=_ConnectorTools(connector_set),  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
        clock=_Clock(),
        model_factory=lambda _level: model,
    )
    conversation_id = uuid4()
    turn_id = uuid4()
    operation = _request_operation(conversation_id, turn_id)
    request = ConversationTurnCreateRequest(
        turn_id=turn_id,
        response_id=uuid4(),
        user_query=query,
        locale=locale,  # type: ignore[arg-type]
        time_zone=time_zone,
    )
    return [
        event
        async for event in runtime.stream(
            request=request,
            actor=Actor(
                id=7,
                email="researcher@example.com",
                status="active",
                email_verified=True,
            ),
            executor=_Executor(),  # type: ignore[arg-type]
            conversation_scope=scope or _scope(),
            context_snapshot=_snapshot(dispatcher),
            conversation_id=conversation_id,
            client_ip="127.0.0.1",
            request_operation=operation,
            correlation_id=operation.trace.correlation_id,
            user_operation_id=operation.trace.operation_id,
            mentioned_annotations=None,
            history=[],
        )
    ]


def _activities(trace: ConversationTrace) -> list[ConversationActivity]:
    return [entry for entry in trace.entries if entry.kind == "activity"]


def _result(events: list[ConversationAgentStreamEvent]) -> ConversationAgentResult:
    results = [event for event in events if isinstance(event, ConversationAgentResult)]
    assert len(results) == 1
    return results[0]


def _final_text(events: list[ConversationAgentStreamEvent]) -> str:
    return "".join(
        event.delta
        for event in events
        if isinstance(event, ConversationStreamAssistantItemDeltaEvent)
    )


@pytest.fixture(autouse=True)
def _disable_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.llm.conversation_agent.settle_token_usage", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "app.llm.conversation_agent.track_event", lambda *_args, **_kwargs: None
    )


@pytest.mark.asyncio
async def test_zero_tool_answer_uses_injected_local_date() -> None:
    seen_instructions: list[str] = []
    seen_output_tools: list[str] = []

    async def direct_answer(
        _messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        seen_instructions.append(info.instructions or "")
        seen_output_tools.extend(tool.name for tool in info.output_tools)
        yield _text_answer("今天是星期四。")

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=direct_answer),
        dispatcher=dispatcher,
        query="今天星期几？",
    )

    assert dispatcher.calls == []
    assert seen_output_tools == []
    assert [
        "result" if isinstance(event, ConversationAgentResult) else event.type
        for event in events
    ] == [
        "assistant_candidate_start",
        "assistant_candidate_delta",
        "assistant_item_start",
        "assistant_item_delta",
        "assistant_item_complete",
        "result",
    ]
    assert isinstance(events[4], ConversationStreamAssistantItemCompleteEvent)
    assert events[4].item.phase == "final"
    assert "2026-08-06" in seen_instructions[0]
    assert "Asia/Shanghai" in seen_instructions[0]
    assert _result(events).trace is None
    assert all(not isinstance(event, dict) for event in events)


@pytest.mark.asyncio
async def test_plain_text_terminal_streams_candidate_after_classification() -> None:
    answer = (
        "A structured final answer can reach the user while its tool arguments "
        "are still arriving from the model, without publishing the held suffix."
    )

    async def streamed_answer(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        yield answer[:46]
        yield answer[46:]

    events = await _events(
        model=FunctionModel(stream_function=streamed_answer),
        dispatcher=_Dispatcher(),
        query="Stream the answer",
        locale="en",
        time_zone="UTC",
    )

    candidate_start = next(
        event
        for event in events
        if isinstance(event, ConversationStreamAssistantCandidateStartEvent)
    )
    candidate_deltas = [
        event.delta
        for event in events
        if isinstance(event, ConversationStreamAssistantCandidateDeltaEvent)
    ]
    final_complete_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
        and event.item.phase == "final"
    )
    last_candidate_index = max(
        index
        for index, event in enumerate(events)
        if isinstance(event, ConversationStreamAssistantCandidateDeltaEvent)
    )

    assert candidate_deltas
    assert "".join(candidate_deltas) == answer
    assert last_candidate_index < final_complete_index
    final_item = events[final_complete_index]
    assert isinstance(final_item, ConversationStreamAssistantItemCompleteEvent)
    assert final_item.item.id == candidate_start.item_id
    assert final_item.item.content == answer


@pytest.mark.parametrize(
    "term",
    [
        "source_keys",
        "private marker",
        "initial answer packet",
        "scholens_cite",
    ],
)
def test_candidate_holds_every_private_protocol_chunk_boundary(term: str) -> None:
    for boundary in range(1, len(term)):
        value = f"Safe answer. {term[:boundary]}"
        assert _unsafe_candidate_suffix_length(value) == boundary


def test_candidate_holds_every_visible_citation_chunk_boundary() -> None:
    citation = "[A12, A3]"
    for boundary in range(1, len(citation)):
        value = f"Safe answer. {citation[:boundary]}"
        assert _unsafe_candidate_suffix_length(value) == boundary


def test_candidate_does_not_delay_an_ordinary_short_answer() -> None:
    assert _unsafe_candidate_suffix_length("Done.") == 0


@pytest.mark.asyncio
async def test_text_before_tool_is_completed_as_progress_before_activity() -> None:
    async def staged_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield "I will inspect the available research."
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"reasoning compression"}',
                    tool_call_id="search-progress",
                )
            }
            return
        yield _grounded_text_answer("Final answer.", info)

    events = await _events(
        model=FunctionModel(stream_function=staged_answer),
        dispatcher=_Dispatcher(),
        query="Research this topic",
        locale="en",
        time_zone="UTC",
    )

    types = [
        "result" if isinstance(event, ConversationAgentResult) else event.type
        for event in events
    ]
    progress_complete_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
        and event.item.phase == "progress"
    )
    first_activity_index = types.index("activity")
    assert progress_complete_index < first_activity_index
    progress_event = events[progress_complete_index]
    assert isinstance(progress_event, ConversationStreamAssistantItemCompleteEvent)
    assert progress_event.item.content == ("I will inspect the available research.")
    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert [(entry.kind, entry.sequence) for entry in trace.entries] == [
        ("progress", 1),
        ("activity", 2),
    ]
    final = [
        event.item
        for event in events
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
        and event.item.phase == "final"
    ]
    assert final == [
        ConversationAssistantItem(
            id=final[0].id,
            sequence=3,
            phase="final",
            content="Final answer.",
        )
    ]


@pytest.mark.asyncio
async def test_progress_is_bounded_without_breaking_the_terminal_answer() -> None:
    long_progress = "p" * 4_500

    async def staged_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield long_progress
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"bounded progress"}',
                    tool_call_id="search-bounded",
                )
            }
            return
        yield _grounded_text_answer("Final answer after bounded progress.", info)

    events = await _events(
        model=FunctionModel(stream_function=staged_answer),
        dispatcher=_Dispatcher(),
        query="Research this topic",
        locale="en",
        time_zone="UTC",
    )

    progress_items = [
        event.item
        for event in events
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
        and event.item.phase == "progress"
    ]
    assert [len(item.content) for item in progress_items] == [4_000]
    assert _result(events).trace is not None
    assert _final_text(events).endswith("Final answer after bounded progress.")


@pytest.mark.asyncio
async def test_hidden_only_pre_tool_text_does_not_emit_an_empty_item() -> None:
    async def staged_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            nonce_match = re.search(
                r"SCHOLENS_CITE:([0-9a-f]+):1", info.instructions or ""
            )
            assert nonce_match is not None
            yield f"[[SCHOLENS_CITE:{nonce_match.group(1)}:1]]"
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"hidden marker"}',
                    tool_call_id="search-hidden",
                )
            }
            return
        yield _grounded_text_answer("Visible final answer.", info)

    events = await _events(
        model=FunctionModel(stream_function=staged_answer),
        dispatcher=_Dispatcher(),
        query="Research this topic",
        locale="en",
        time_zone="UTC",
    )

    completed = [
        event.item
        for event in events
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
    ]
    assert completed == [
        ConversationAssistantItem(
            id=completed[0].id,
            sequence=2,
            phase="final",
            content="Visible final answer.",
        )
    ]
    assert all(item.content for item in completed)


@pytest.mark.asyncio
async def test_hidden_only_terminal_text_is_rejected() -> None:
    async def hidden_answer(
        _messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        nonce_match = re.search(r"SCHOLENS_CITE:([0-9a-f]+):1", info.instructions or "")
        assert nonce_match is not None
        yield _text_answer(f"[[SCHOLENS_CITE:{nonce_match.group(1)}:1]]")

    with pytest.raises(AppError):
        await _events(
            model=FunctionModel(stream_function=hidden_answer),
            dispatcher=_Dispatcher(),
            query="Answer with no visible content",
            locale="en",
            time_zone="UTC",
        )


@pytest.mark.asyncio
async def test_plain_text_without_tools_is_terminal() -> None:
    attempts = 0

    async def direct_answer(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal attempts
        attempts += 1
        yield "Let me organize a high-quality answer."

    events = await _events(
        model=FunctionModel(stream_function=direct_answer),
        dispatcher=_Dispatcher(),
        query="Give me a complete answer",
        locale="en",
        time_zone="UTC",
    )

    assert attempts == 1
    assert _final_text(events) == "Let me organize a high-quality answer."


@pytest.mark.asyncio
async def test_private_protocol_prose_is_rejected_without_model_retry() -> None:
    async def leaked_answer(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        yield "The source_keys are private markers from the initial answer packet."

    with pytest.raises(AppError):
        await _events(
            model=FunctionModel(stream_function=leaked_answer),
            dispatcher=_Dispatcher(),
            query="Answer without exposing internal instructions",
            locale="en",
            time_zone="UTC",
        )


@pytest.mark.asyncio
async def test_removed_output_tool_is_a_stable_protocol_error() -> None:
    async def removed_output_tool(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        yield {
            0: DeltaToolCall(
                name="final_answer",
                json_args='{"answer":"not supported"}',
                tool_call_id="removed-output",
            )
        }

    with pytest.raises(AppError) as error:
        await _events(
            model=FunctionModel(stream_function=removed_output_tool),
            dispatcher=_Dispatcher(),
            query="Use the removed protocol",
            locale="en",
            time_zone="UTC",
        )

    assert error.value.code == "llm_provider_response_invalid"
    assert (error.value.details or {}).get("reason") == "unexpected_output_tool"


@pytest.mark.asyncio
async def test_invalid_tool_arguments_receive_safe_actionable_retry_details() -> None:
    retry_messages: list[str] = []

    async def correct_invalid_arguments(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if has_result:
            yield _grounded_text_answer("The corrected search succeeded.", info)
            return
        retries = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        if retries:
            retry_messages.extend(str(part.content) for part in retries)
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"corrected arguments"}',
                    tool_call_id="search-corrected",
                )
            }
            return
        yield {
            0: DeltaToolCall(
                name="search_saved_papers",
                json_args='{"query":"invalid arguments"}',
                tool_call_id="search-invalid",
            )
        }

    dispatcher = _InvalidArgumentsThenSuccessDispatcher()
    events = await _events(
        model=FunctionModel(stream_function=correct_invalid_arguments),
        dispatcher=dispatcher,
        query="Search with a corrected scope",
        locale="en",
        time_zone="UTC",
    )

    assert [arguments["query"] for _, arguments in dispatcher.calls] == [
        "invalid arguments",
        "corrected arguments",
    ]
    assert any("scope" in message for message in retry_messages)
    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert [activity.state for activity in _activities(trace)] == [
        "failed",
        "succeeded",
    ]
    assert _final_text(events) == "The corrected search succeeded."


@pytest.mark.asyncio
async def test_research_tool_streams_sanitized_activity_and_references() -> None:
    async def research_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"reasoning compression"}',
                    tool_call_id="search-1",
                )
            }
            return
        nonce_match = re.search(r"SCHOLENS_CITE:([0-9a-f]+):1", info.instructions or "")
        assert nonce_match is not None
        yield _text_answer(f"Grounded claim[[SCHOLENS_CITE:{nonce_match.group(1)}:1]]")

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=research_answer),
        dispatcher=dispatcher,
        query="研究思维链压缩技术",
    )

    activities = [
        event.activity
        for event in events
        if isinstance(event, ConversationStreamActivityEvent)
    ]
    assert activities == [
        ConversationActivity(
            id="search-1",
            sequence=1,
            category="search",
            state="running",
            subject="reasoning compression",
        ),
        ConversationActivity(
            id="search-1",
            sequence=1,
            category="search",
            state="succeeded",
            subject="reasoning compression",
            source_count=1,
            artifact_count=0,
        ),
    ]
    assert dispatcher.calls == [
        ("search_saved_papers", {"query": "reasoning compression"})
    ]
    assert _final_text(events) == "Grounded claim"
    references = next(
        ReferenceBundle.model_validate(event.references)
        for event in events
        if isinstance(event, ConversationStreamReferencesEvent)
    )
    assert len(references.sources) == 1
    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert trace.citation_summary is not None
    assert trace.citation_summary.source_count == 1


@pytest.mark.asyncio
async def test_source_backed_answer_publishes_safe_prose_without_citation_retry() -> (
    None
):
    final_attempts = 0

    async def research_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        nonlocal final_attempts
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"citation regression"}',
                    tool_call_id="search-citation-regression",
                )
            }
            return

        final_attempts += 1
        yield _text_answer("Grounded claim [A1]")

    events = await _events(
        model=FunctionModel(stream_function=research_answer),
        dispatcher=_Dispatcher(),
        query="Research this with citations",
        locale="en",
        time_zone="UTC",
    )

    assert final_attempts == 1
    assert _final_text(events) == "Grounded claim"
    assert "[A1]" not in str(events)
    references = next(
        ReferenceBundle.model_validate(event.references)
        for event in events
        if isinstance(event, ConversationStreamReferencesEvent)
    )
    assert len(references.sources) == 0
    reference_event = next(
        event
        for event in events
        if isinstance(event, ConversationStreamReferencesEvent)
    )
    assert reference_event.citation_summary is not None
    assert reference_event.citation_summary.status == "unavailable"


@pytest.mark.asyncio
async def test_exhausted_citation_repair_publishes_safe_answer() -> None:
    async def always_invalid(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        if not any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"resilience"}',
                    tool_call_id="search-resilience",
                )
            }
            return
        assert info.instructions is not None
        yield _text_answer("Safe answer [1]")

    events = await _events(
        model=FunctionModel(stream_function=always_invalid),
        dispatcher=_Dispatcher(),
        query="Test citation resilience",
        locale="en",
        time_zone="UTC",
    )
    final = [
        event.item.content
        for event in events
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
        and event.item.phase == "final"
    ]
    assert final == ["Safe answer"]
    references = [
        event
        for event in events
        if isinstance(event, ConversationStreamReferencesEvent)
    ]
    assert len(references) == 1
    assert references[0].references == {"annotations": [], "sources": []}
    assert references[0].citation_summary is not None
    assert references[0].citation_summary.status == "unavailable"


@pytest.mark.asyncio
async def test_tool_failure_can_continue_to_a_natural_answer() -> None:
    async def answer_after_failure(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"unavailable topic"}',
                    tool_call_id="failed-search",
                )
            }
            return
        yield _text_answer("I could not search, but here is what I can explain.")

    dispatcher = _Dispatcher(fail=True)
    events = await _events(
        model=FunctionModel(stream_function=answer_after_failure),
        dispatcher=dispatcher,
        query="Explain the topic even if search is unavailable",
        locale="en",
        time_zone="UTC",
    )

    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert _activities(trace)[-1].state == "failed"
    assert any(
        isinstance(event, ConversationStreamAssistantItemDeltaEvent) for event in events
    )


@pytest.mark.asyncio
async def test_multiple_tools_preserve_order_and_terminal_state() -> None:
    async def multi_tool_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if result_count < 2:
            sequence = result_count + 1
            yield f"Research stage {sequence}."
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args=f'{{"query":"topic {sequence}"}}',
                    tool_call_id=f"search-{sequence}",
                )
            }
            return
        yield _grounded_text_answer("Combined answer.", info)

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=multi_tool_answer),
        dispatcher=dispatcher,
        query="Compare two research directions",
        locale="en",
        time_zone="UTC",
    )

    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert [(entry.kind, entry.sequence) for entry in trace.entries] == [
        ("progress", 1),
        ("activity", 2),
        ("progress", 3),
        ("activity", 4),
    ]
    assert [activity.sequence for activity in _activities(trace)] == [2, 4]
    assert [activity.state for activity in _activities(trace)] == [
        "succeeded",
        "succeeded",
    ]
    assert [arguments["query"] for _, arguments in dispatcher.calls] == [
        "topic 1",
        "topic 2",
    ]
    completed_items = [
        event.item
        for event in events
        if isinstance(event, ConversationStreamAssistantItemCompleteEvent)
    ]
    assert [item.phase for item in completed_items] == [
        "progress",
        "progress",
        "final",
    ]
    assert [item.content for item in completed_items] == [
        "Research stage 1.",
        "Research stage 2.",
        "Combined answer.",
    ]
    assert "tool_name" not in str(events)


@pytest.mark.asyncio
async def test_duplicate_tool_call_is_blocked_before_dispatch() -> None:
    async def duplicate_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if result_count < 2:
            sequence = result_count + 1
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"same topic"}',
                    tool_call_id=f"search-{sequence}",
                )
            }
            return
        yield _grounded_text_answer("Used the first result.", info)

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=duplicate_answer),
        dispatcher=dispatcher,
        query="Search once, not twice",
        locale="en",
        time_zone="UTC",
    )

    assert len(dispatcher.calls) == 1
    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert [activity.state for activity in _activities(trace)] == [
        "succeeded",
        "failed",
    ]


@pytest.mark.asyncio
async def test_repeatable_tool_call_can_dispatch_with_identical_arguments() -> None:
    async def repeated_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if result_count < 2:
            sequence = result_count + 1
            yield {
                0: DeltaToolCall(
                    name="search_saved_papers",
                    json_args='{"query":"same topic"}',
                    tool_call_id=f"wait-{sequence}",
                )
            }
            return
        yield _grounded_text_answer("Both bounded waits completed.", info)

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=repeated_answer),
        dispatcher=dispatcher,
        query="Wait twice when needed",
        locale="en",
        time_zone="UTC",
        allow_repeated_calls=True,
    )

    assert len(dispatcher.calls) == 2
    trace = _result(events).trace
    assert isinstance(trace, ConversationTrace)
    assert [activity.state for activity in _activities(trace)] == [
        "succeeded",
        "succeeded",
    ]


@pytest.mark.asyncio
async def test_unauthorized_tool_is_not_exposed_or_dispatched() -> None:
    async def answer_without_tool(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        yield _text_answer("No tool available.")

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=answer_without_tool),
        dispatcher=dispatcher,
        query="Search my papers",
        locale="en",
        time_zone="UTC",
        scope=ConversationChatScope(
            scope_type=ConversationScopeType.PROJECT,
            project_id=uuid4(),
            document_id=None,
            paper_context=LibraryPaperCollection(),
            tool_permissions=frozenset({WorkspacePermission.WRITE}),
            title_is_default=False,
        ),
    )

    assert dispatcher.calls == []
    assert _result(events).trace is None


@pytest.mark.asyncio
async def test_cancellation_propagates_without_becoming_a_product_error() -> None:
    entered = asyncio.Event()

    async def blocked_answer(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        entered.set()
        await asyncio.Event().wait()
        yield _text_answer("unreachable")

    dispatcher = _Dispatcher()
    task = asyncio.create_task(
        _events(
            model=FunctionModel(stream_function=blocked_answer),
            dispatcher=dispatcher,
            query="Wait",
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_agent_enforces_maximum_tool_call_budget() -> None:
    async def endless_tools(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        yield {
            0: DeltaToolCall(
                name="search_saved_papers",
                json_args=f'{{"query":"topic {result_count}"}}',
                tool_call_id=f"search-{result_count}",
            )
        }

    with pytest.raises(AppError):
        await _events(
            model=FunctionModel(stream_function=endless_tools),
            dispatcher=_Dispatcher(),
            query="Never stop searching",
            locale="en",
            time_zone="UTC",
        )


def test_request_rejects_non_iana_time_zone() -> None:
    with pytest.raises(ValueError, match="valid IANA time zone"):
        ConversationTurnCreateRequest(
            turn_id=uuid4(),
            response_id=uuid4(),
            user_query="What time is it?",
            locale="en",
            time_zone="Shanghai",
        )


async def _capture_instructions(
    *,
    query: str = "What can you do?",
    scope: ConversationChatScope | None = None,
    connector_set: ResolvedConnectorToolSet | None = None,
) -> str:
    seen: list[str] = []

    async def direct_answer(
        _messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        seen.append(info.instructions or "")
        yield _text_answer("Understood.")

    await _events(
        model=FunctionModel(stream_function=direct_answer),
        dispatcher=_Dispatcher(),
        query=query,
        locale="en",
        time_zone="UTC",
        scope=scope,
        connector_set=connector_set,
    )
    assert len(seen) == 1
    return seen[0]


@pytest.mark.parametrize(
    ("scope_type", "project_id", "document_id", "paper_context", "gravity_phrase"),
    [
        (
            ConversationScopeType.GLOBAL,
            None,
            None,
            LibraryPaperCollection(),
            "broad Home research flow",
        ),
        (
            ConversationScopeType.PROJECT,
            uuid4(),
            None,
            SelectedPaperCollection(project_ids=[uuid4()]),
            "project-centered research flow",
        ),
        (
            ConversationScopeType.PAPER,
            None,
            uuid4(),
            SelectedPaperCollection(document_ids=[uuid4()]),
            "deep-reading flow",
        ),
    ],
)
@pytest.mark.asyncio
async def test_instructions_encode_scope_gravity_and_attention(
    scope_type: ConversationScopeType,
    project_id: UUID | None,
    document_id: UUID | None,
    paper_context: Any,
    gravity_phrase: str,
) -> None:
    scope = ConversationChatScope(
        scope_type=scope_type,
        project_id=project_id,
        document_id=document_id,
        paper_context=paper_context,
        tool_permissions=frozenset({WorkspacePermission.READ}),
        title_is_default=False,
    )
    instructions = await _capture_instructions(scope=scope)

    assert gravity_phrase in instructions
    assert "not a capability wall" in instructions
    assert f'"scope_type": "{scope_type.value}"' in instructions
    assert f'"kind": "{paper_context.kind}"' in instructions
    if isinstance(paper_context, SelectedPaperCollection):
        for item in (*paper_context.project_ids, *paper_context.document_ids):
            assert str(item) in instructions


@pytest.mark.asyncio
async def test_instructions_expose_resolved_connector_tools() -> None:
    connector_set = ResolvedConnectorToolSet(
        declarations=(
            {
                "name": "search_papers",
                "description": "Discover external literature.",
                "parameters": {"type": "object", "properties": {}},
            },
        )
    )
    instructions = await _capture_instructions(connector_set=connector_set)

    assert "connector_tools: search_papers" in instructions
    assert "connector_issues: none" in instructions


@pytest.mark.asyncio
async def test_instructions_expose_connector_omissions() -> None:
    connector_set = ResolvedConnectorToolSet(
        issues=(
            ConnectorToolIssue(
                provider=IntegrationProvider.SCHOLIGHT,
                code="connector_unavailable",
                message="Scholight is unavailable",
            ),
        )
    )
    instructions = await _capture_instructions(connector_set=connector_set)

    assert "connector_tools: none available" in instructions
    assert "connector_issues: scholight:connector_unavailable" in instructions


@pytest.mark.asyncio
async def test_instructions_prefer_tools_for_stored_research_facts() -> None:
    instructions = await _capture_instructions()

    assert "solving requests with the available tools" in instructions
    assert "inspect with tools before claiming absence" in instructions
    assert "no mandatory" in instructions
    assert "A direct answer is allowed" in instructions
    assert "External literature discovery" in instructions
