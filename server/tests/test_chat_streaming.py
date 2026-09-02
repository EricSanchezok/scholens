"""Post-header chat failures use one stable public event."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from uuid import UUID
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_keepalive,
    stream_with_stable_error,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationStreamAssistantItemDeltaEvent,
    ConversationStreamCompleteEvent,
)


RESPONSE_ID = UUID("00000000-0000-0000-0000-000000000002")


def _payload(event: str) -> dict[str, object]:
    data = next(
        line.removeprefix("data: ")
        for line in event.splitlines()
        if line.startswith("data: ")
    )
    value = json.loads(data)
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_keepalive_comment_does_not_cancel_pending_event() -> None:
    release = asyncio.Event()

    async def delayed_stream():
        await release.wait()
        yield "typed-event"

    stream = stream_with_keepalive(delayed_stream(), interval_seconds=0.001)
    assert await anext(stream) == ": keepalive\n\n"
    release.set()
    assert await anext(stream) == "typed-event"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_keepalive_drives_the_source_from_one_task_for_its_whole_lifecycle() -> (
    None
):
    release = asyncio.Event()
    source_task: asyncio.Task[object] | None = None

    async def task_bound_stream():
        nonlocal source_task
        source_task = asyncio.current_task()
        try:
            yield "first"
            await release.wait()
            assert asyncio.current_task() is source_task
            yield "second"
        finally:
            assert asyncio.current_task() is source_task

    stream = stream_with_keepalive(task_bound_stream(), interval_seconds=0.001)
    assert await anext(stream) == "first"
    assert await anext(stream) == ": keepalive\n\n"
    release.set()
    assert await anext(stream) == "second"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_keepalive_can_publish_a_product_phase_without_provider_details() -> None:
    release = asyncio.Event()

    async def delayed_stream():
        await release.wait()
        yield "typed-event"

    stream = stream_with_keepalive(
        delayed_stream(),
        interval_seconds=0.001,
        on_timeout=lambda: 'event: phase\ndata: {"phase":"tool"}\n\n',
    )
    phase = await anext(stream)
    assert phase.startswith("event: phase\n")
    assert ": keepalive" not in phase
    release.set()
    assert await anext(stream) == "typed-event"


@pytest.mark.asyncio
async def test_stream_failure_is_redacted_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_stream():
        yield "first"
        raise RuntimeError("provider secret")

    track_event = MagicMock()
    recorder = MagicMock()
    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.chat_streaming.track_event",
        track_event,
    )

    events = [
        event
        async for event in stream_with_stable_error(
            failing_stream(),
            response_id=RESPONSE_ID,
            event_name="chat_error",
            user_id=7,
            properties={"conversation_id": "conversation"},
            diagnostic_recorder=recorder,
        )
    ]

    assert events[0] == "first"
    failure = _payload(events[-1])
    assert failure["type"] == "error"
    assert failure["error"]["code"] == "chat_stream_failed"
    assert failure["error"]["kind"] == "dependency_failure"
    assert failure["error"]["retryable"] is True
    assert "provider secret" not in events[-1]
    assert track_event.call_args.kwargs["properties"]["error_type"] == "RuntimeError"
    snapshot = recorder.record.call_args.args[0]
    assert str(snapshot.id) == failure["error"]["diagnostic_id"]
    assert snapshot.sections["failure"]["code"] == "chat_stream_failed"


@pytest.mark.asyncio
async def test_stream_requires_explicit_complete_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def incomplete_stream():
        yield encode_conversation_sse(
            ConversationStreamAssistantItemDeltaEvent(
                response_id=RESPONSE_ID,
                item_id="assistant:turn:1",
                delta="partial",
            )
        )

    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.chat_streaming.track_event",
        MagicMock(),
    )
    events = [
        event
        async for event in stream_with_stable_error(
            incomplete_stream(),
            response_id=RESPONSE_ID,
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    failure = _payload(events[-1])
    assert failure["error"]["code"] == "stream_incomplete"


@pytest.mark.asyncio
async def test_complete_stream_has_no_error_event() -> None:
    async def completed_stream():
        yield encode_conversation_sse(
            ConversationStreamAssistantItemDeltaEvent(
                response_id=RESPONSE_ID,
                item_id="assistant:turn:1",
                delta="answer",
            )
        )
        yield encode_conversation_sse(
            ConversationStreamCompleteEvent(
                turn_id="00000000-0000-0000-0000-000000000001",
                response_id=RESPONSE_ID,
            )
        )

    events = [
        event
        async for event in stream_with_stable_error(
            completed_stream(),
            response_id=RESPONSE_ID,
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    assert _payload(events[-1])["type"] == "complete"
