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


class _ChatData:
    def __init__(self, request: ConversationTurnCreateRequest) -> None:
        self.request = request
        self.suggestions: list[str] | None = None
        self.completed = False

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

    def start_turn(self, **_: object) -> ConversationTurnStart:
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

    def complete_turn(self, **_: object) -> ConversationTurnCompletion:
        self.completed = True
        return ConversationTurnCompletion(
            response=PersistedChatResponse(
                id=self.request.response_id,
                turn_id=self.request.turn_id,
                variant_index=1,
                status="completed",
                content="Answer",
                references=None,
                trace=None,
            ),
            created=True,
            citation_ids=(),
        )

    def save_turn_suggestions(
        self, *, suggestions: tuple[str, str, str], **_: object
    ) -> bool:
        self.suggestions = list(suggestions)
        return True

    def finish_response(self, **_: object) -> None:
        return None


class _Conversations:
    def __init__(self, chat_data: _ChatData) -> None:
        self._chat_data = chat_data

    def turns(self, **_: object) -> ConversationTurnsResponse:
        request = self._chat_data.request
        return ConversationTurnsResponse(
            items=[
                ConversationTurnResponse(
                    id=request.turn_id,
                    user_query=request.user_query,
                    contexts=[],
                    scope=None,
                    reasoning_level="standard",
                    locale="en",
                    time_zone="UTC",
                    sequence=1,
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
                        )
                    ],
                )
            ]
        )


class _Executor:
    def __init__(self, chat_data: _ChatData) -> None:
        self.capabilities = SimpleNamespace(
            conversation_chat_data=chat_data,
            conversations=_Conversations(chat_data),
        )

    def query(self, callback):
        return callback(self.capabilities)

    def command(self, callback):
        return callback(self.capabilities)


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
