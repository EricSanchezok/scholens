from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.bootstrap.adapters.conversation_chat import stream_conversation_agent
from app.helpers.ai_limits import AILimitExceeded
from app.modules.conversations.application.chat import (
    ConversationChatScope,
    ConversationContextSnapshot,
    ConversationTurnCompletion,
    ConversationTurnStart,
    MentionScope,
    PersistedChatResponse,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationResponseVariantResponse,
    ConversationTurnResponse,
    ConversationTurnsResponse,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationStreamAssistantItemCompleteEvent,
    ConversationTurnCreateRequest,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ConversationScopeType


def _payload(event: str) -> dict[str, Any]:
    data = next(
        line.removeprefix("data: ")
        for line in event.splitlines()
        if line.startswith("data: ")
    )
    payload = json.loads(data)
    assert isinstance(payload, dict)
    return payload


@dataclass
class _SuggestionGenerator:
    started: asyncio.Event
    release: asyncio.Event

    async def generate(self, _seed: object) -> list[str]:
        self.started.set()
        await self.release.wait()
        return ["Deepen?", "Verify?", "Apply?"]


class _Runtime:
    def __init__(self, suggestions_started: asyncio.Event) -> None:
        self._suggestions_started = suggestions_started

    async def stream(self, **kwargs: object):
        await asyncio.wait_for(self._suggestions_started.wait(), timeout=0.5)
        request = kwargs["request"]
        assert isinstance(request, ConversationTurnCreateRequest)
        yield ConversationStreamAssistantItemCompleteEvent(
            response_id=request.response_id,
            item=ConversationAssistantItem(
                id=f"assistant:{request.turn_id}:1",
                sequence=1,
                phase="final",
                content="Answer",
            ),
        )


class _FailingRuntime:
    def __init__(self, suggestions_started: asyncio.Event) -> None:
        self._suggestions_started = suggestions_started

    async def stream(self, **_: object):
        await asyncio.wait_for(self._suggestions_started.wait(), timeout=0.5)
        if False:
            yield None
        raise RuntimeError("agent failed")


class _BlockedRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, **_: object):
        self.started.set()
        await self.release.wait()
        if False:
            yield None


class _ChatData:
    def __init__(self, request: ConversationTurnCreateRequest) -> None:
        self.request = request
        self.suggestions: list[str] | None = None
        self.completed = False
        self.complete_duration_ms: int | None = None
        self.finished: tuple[str, int] | None = None
        self.start_calls = 0
        self.selected_path = [uuid4()]
        self.path_revision = 3
        self.paper_context: dict[str, object] = {"kind": "library"}

    def prepare(self, **_: object) -> ConversationChatScope:
        return ConversationChatScope(
            scope_type=ConversationScopeType.GLOBAL,
            project_id=None,
            document_id=None,
            paper_context=LibraryPaperCollection(),
            tool_permissions=frozenset(),
            title_is_default=False,
        )

    def mentions(self, **_: object) -> MentionScope:
        return MentionScope(snapshot=None, annotation_threads=None)

    def context(self, **_: object) -> ConversationContextSnapshot:
        return ConversationContextSnapshot(
            papers=[], projects=[], available_document_count=0
        )

    def start_turn(self, **kwargs: object) -> ConversationTurnStart:
        self.start_calls += 1
        if kwargs.get("generation_kind") == "branch":
            self.paper_context = dict(kwargs["paper_context"])  # type: ignore[arg-type]
            self.selected_path = [self.request.turn_id]
            self.path_revision += 1
        return ConversationTurnStart(
            turn_id=self.request.turn_id,
            response=PersistedChatResponse(
                id=self.request.response_id,
                turn_id=self.request.turn_id,
                variant_index=1,
                status="running",
                content="",
                references=None,
                trace=None,
                duration_ms=None,
            ),
            turn_operation_id=uuid4(),
            correlation_id=uuid4(),
            turn_created=True,
            response_created=True,
            generation_kind="initial",
            suggestions=(),
        )

    def history(self, **_: object) -> list[object]:
        return []

    def complete_turn(self, **kwargs: object) -> ConversationTurnCompletion:
        self.completed = True
        self.complete_duration_ms = int(kwargs["duration_ms"])
        return ConversationTurnCompletion(
            response=PersistedChatResponse(
                id=self.request.response_id,
                turn_id=self.request.turn_id,
                variant_index=1,
                status="completed",
                content="Answer",
                references=None,
                trace=None,
                duration_ms=self.complete_duration_ms,
            ),
            created=True,
            citation_ids=(),
        )

    def save_turn_suggestions(
        self, *, suggestions: tuple[str, str, str], **_: object
    ) -> bool:
        self.suggestions = list(suggestions)
        return True

    def finish_response(self, **kwargs: object) -> None:
        self.finished = (str(kwargs["status"]), int(kwargs["duration_ms"]))


class _Conversations:
    def __init__(self, chat_data: _ChatData) -> None:
        self._chat_data = chat_data

    def turns(self, **_: object) -> ConversationTurnsResponse:
        request = self._chat_data.request
        return ConversationTurnsResponse(
            items=[
                ConversationTurnResponse(
                    id=request.turn_id,
                    parent_turn_id=None,
                    user_query=request.user_query,
                    contexts=[],
                    paper_context={"kind": "library"},
                    reasoning_level="standard",
                    locale="en",
                    time_zone="UTC",
                    depth=1,
                    branch={"index": 1, "count": 1},
                    selected_response_id=request.response_id,
                    suggestions=self._chat_data.suggestions,
                    responses=[
                        ConversationResponseVariantResponse(
                            id=request.response_id,
                            variant_index=1,
                            status="completed",
                            content="Answer",
                            references=None,
                            artifacts=None,
                            trace=None,
                            duration_ms=self._chat_data.complete_duration_ms,
                        )
                    ],
                )
            ],
            path_revision=1,
        )


class _Executor:
    def __init__(self, chat_data: _ChatData) -> None:
        self.chat_data = chat_data
        self.capabilities = SimpleNamespace(
            conversation_chat_data=chat_data,
            conversations=_Conversations(chat_data),
        )
        self.command_calls = 0

    def query(self, callback):
        return callback(self.capabilities)

    def command(self, callback):
        self.command_calls += 1
        snapshot = (
            list(self.chat_data.selected_path),
            self.chat_data.path_revision,
            dict(self.chat_data.paper_context),
        )
        try:
            return callback(self.capabilities)
        except BaseException:
            (
                self.chat_data.selected_path,
                self.chat_data.path_revision,
                self.chat_data.paper_context,
            ) = snapshot
            raise


def _patch_stream_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def acquire(**_: object) -> object:
        return object()

    async def no_op(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.enforce_rate_limit", no_op
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.acquire_concurrency", acquire
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.release_concurrency", no_op
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.llm_usage_context",
        lambda **_: nullcontext(),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.track_event", lambda *_, **__: None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["quota", "rate", "capacity"])
async def test_branch_preflight_failure_preserves_authoritative_state(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Edited question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    executor = _Executor(chat_data)
    original_state = (
        list(chat_data.selected_path),
        chat_data.path_revision,
        dict(chat_data.paper_context),
    )

    async def no_op(*_: object, **__: object) -> None:
        return None

    async def fail_limit(*_: object, **__: object) -> None:
        raise AILimitExceeded(
            "rate_limit_exceeded"
            if failure_stage == "rate"
            else "interactive_concurrency_exceeded"
        )

    if failure_stage == "quota":

        def fail_prepare(**_: object) -> ConversationChatScope:
            raise AppError(
                code="token_quota_exceeded",
                message="Token quota exceeded",
                kind=FailureKind.RATE_LIMITED,
            )

        chat_data.prepare = fail_prepare  # type: ignore[method-assign]
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_chat.enforce_rate_limit", no_op
        )
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_chat.acquire_concurrency", no_op
        )
    else:
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_chat.enforce_rate_limit",
            fail_limit if failure_stage == "rate" else no_op,
        )
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_chat.acquire_concurrency",
            fail_limit if failure_stage == "capacity" else no_op,
        )

    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )
    with pytest.raises(AppError) as exc_info:
        await stream_conversation_agent(
            request,
            conversation_id=uuid4(),
            client_ip="127.0.0.1",
            executor=executor,
            current_user=Actor(
                id=7,
                email="reader@example.com",
                status="active",
                email_verified=True,
            ),
            runtime=_FailingRuntime(asyncio.Event()),
            operation=operation,
            operation_factory=SimpleNamespace(resume=lambda **_: operation),
            suggestion_generator=_SuggestionGenerator(
                asyncio.Event(),
                asyncio.Event(),
            ),
            generation_kind="branch",
            branch_from_turn_id=chat_data.selected_path[0],
            paper_context_snapshot=LibraryPaperCollection(),
        )

    assert exc_info.value.code in {
        "token_quota_exceeded",
        "rate_limit_exceeded",
        "interactive_concurrency_exceeded",
    }
    assert executor.command_calls == 0
    assert chat_data.start_calls == 0
    assert (
        chat_data.selected_path,
        chat_data.path_revision,
        chat_data.paper_context,
    ) == original_state


@pytest.mark.asyncio
async def test_successful_branch_switches_context_and_path_in_accept_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Edited question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    source_turn_id = chat_data.selected_path[0]
    chat_data.paper_context = {"kind": "selection", "document_ids": [str(uuid4())]}
    executor = _Executor(chat_data)
    _patch_stream_dependencies(monkeypatch)
    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )

    source = await stream_conversation_agent(
        request,
        conversation_id=uuid4(),
        client_ip="127.0.0.1",
        executor=executor,
        current_user=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        runtime=_FailingRuntime(asyncio.Event()),
        operation=operation,
        operation_factory=SimpleNamespace(resume=lambda **_: operation),
        suggestion_generator=_SuggestionGenerator(asyncio.Event(), asyncio.Event()),
        generation_kind="branch",
        branch_from_turn_id=source_turn_id,
        paper_context_snapshot=LibraryPaperCollection(),
    )

    assert executor.command_calls == 1
    assert chat_data.start_calls == 1
    assert chat_data.selected_path == [request.turn_id]
    assert chat_data.path_revision == 4
    assert chat_data.paper_context == {"kind": "library"}

    iterator = source.__aiter__()
    assert _payload(await anext(iterator))["type"] == "start"
    await iterator.aclose()


@pytest.mark.asyncio
async def test_turn_id_conflict_rolls_back_acceptance_and_releases_capacity_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Edited question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    executor = _Executor(chat_data)
    lease = object()
    released: list[object] = []

    async def no_op(*_: object, **__: object) -> None:
        return None

    async def acquire(**_: object) -> object:
        return lease

    async def release(value: object, **_: object) -> None:
        released.append(value)

    original_state = (
        list(chat_data.selected_path),
        chat_data.path_revision,
        dict(chat_data.paper_context),
    )

    def reject_start(**kwargs: object) -> ConversationTurnStart:
        chat_data.paper_context = dict(kwargs["paper_context"])  # type: ignore[arg-type]
        chat_data.selected_path = [request.turn_id]
        chat_data.path_revision += 1
        raise AppError(
            code="conversation_turn_conflict",
            message="Turn was already used differently",
            kind=FailureKind.CONFLICT,
        )

    chat_data.start_turn = reject_start  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.enforce_rate_limit", no_op
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.acquire_concurrency", acquire
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.release_concurrency", release
    )
    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )

    with pytest.raises(AppError) as exc_info:
        await stream_conversation_agent(
            request,
            conversation_id=uuid4(),
            client_ip="127.0.0.1",
            executor=executor,
            current_user=Actor(
                id=7,
                email="reader@example.com",
                status="active",
                email_verified=True,
            ),
            runtime=_FailingRuntime(asyncio.Event()),
            operation=operation,
            operation_factory=SimpleNamespace(resume=lambda **_: operation),
            suggestion_generator=_SuggestionGenerator(
                asyncio.Event(),
                asyncio.Event(),
            ),
        )

    assert exc_info.value.code == "conversation_turn_conflict"
    assert executor.command_calls == 1
    assert released == [lease]
    assert (
        chat_data.selected_path,
        chat_data.path_revision,
        chat_data.paper_context,
    ) == original_state


@pytest.mark.asyncio
async def test_suggestions_start_before_answer_and_arrive_after_response_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    started = asyncio.Event()
    release = asyncio.Event()

    _patch_stream_dependencies(monkeypatch)

    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )
    source = await stream_conversation_agent(
        request,
        conversation_id=uuid4(),
        client_ip="127.0.0.1",
        executor=_Executor(chat_data),
        current_user=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        runtime=_Runtime(started),
        operation=operation,
        operation_factory=SimpleNamespace(resume=lambda **_: operation),
        suggestion_generator=_SuggestionGenerator(started, release),
    )

    iterator = source.__aiter__()
    event_types: list[str] = []
    while "response_ready" not in event_types:
        event_types.append(str(_payload(await anext(iterator))["type"]))

    assert started.is_set()
    assert chat_data.completed is True
    assert chat_data.suggestions is None

    release.set()
    async for event in iterator:
        event_types.append(str(_payload(event)["type"]))

    assert event_types.index("response_ready") < event_types.index("suggestions")
    assert event_types[-1] == "complete"
    assert chat_data.suggestions == ["Deepen?", "Verify?", "Apply?"]
    assert chat_data.complete_duration_ms is not None
    assert chat_data.complete_duration_ms >= 0


@pytest.mark.asyncio
async def test_failed_stream_persists_terminal_status_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    started = asyncio.Event()
    release = asyncio.Event()
    _patch_stream_dependencies(monkeypatch)
    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )
    source = await stream_conversation_agent(
        request,
        conversation_id=uuid4(),
        client_ip="127.0.0.1",
        executor=_Executor(chat_data),
        current_user=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        runtime=_FailingRuntime(started),
        operation=operation,
        operation_factory=SimpleNamespace(resume=lambda **_: operation),
        suggestion_generator=_SuggestionGenerator(started, release),
    )

    event_types = [_payload(event)["type"] async for event in source]

    assert event_types == ["start", "error"]
    assert chat_data.finished is not None
    assert chat_data.finished[0] == "failed"
    assert chat_data.finished[1] >= 0


@pytest.mark.asyncio
async def test_cancelled_stream_persists_terminal_status_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Question",
        locale="en",
        time_zone="UTC",
    )
    chat_data = _ChatData(request)
    runtime = _BlockedRuntime()
    suggestions_started = asyncio.Event()
    suggestions_release = asyncio.Event()
    _patch_stream_dependencies(monkeypatch)
    operation = SimpleNamespace(
        trace=SimpleNamespace(operation_id=uuid4(), correlation_id=uuid4()),
        origin="test",
        credential=None,
    )
    source = await stream_conversation_agent(
        request,
        conversation_id=uuid4(),
        client_ip="127.0.0.1",
        executor=_Executor(chat_data),
        current_user=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        runtime=runtime,
        operation=operation,
        operation_factory=SimpleNamespace(resume=lambda **_: operation),
        suggestion_generator=_SuggestionGenerator(
            suggestions_started,
            suggestions_release,
        ),
    )
    iterator = source.__aiter__()
    assert _payload(await anext(iterator))["type"] == "start"
    pending = asyncio.create_task(anext(iterator))
    await asyncio.wait_for(runtime.started.wait(), timeout=0.5)

    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await iterator.aclose()

    assert chat_data.finished is not None
    assert chat_data.finished[0] == "cancelled"
    assert chat_data.finished[1] >= 0
