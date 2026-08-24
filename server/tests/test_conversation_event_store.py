from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.modules.conversations.infrastructure import event_store
from app.bootstrap.adapters.conversation_chat import _is_assistant_candidate_frame
from app.modules.conversations.infrastructure.event_store import (
    ConversationEventStore,
)


class _Redis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, str], int, bool]] = []
        self.expirations: list[tuple[str, int]] = []
        self.reads: list[tuple[dict[str, str], int, int]] = []
        self.pipeline_transactions: list[bool] = []
        self.closed = False

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        self.pipeline_transactions.append(transaction)
        return _Pipeline(self)

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.added.append((key, fields, maxlen, approximate))
        return "1-0"

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations.append((key, seconds))

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        self.reads.append((streams, count, block))
        key = next(iter(streams))
        return [(key, [("2-0", {"sse": "event: complete\ndata: {}\n\n"})])]

    async def aclose(self) -> None:
        self.closed = True


class _Pipeline:
    def __init__(self, redis: _Redis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def xadd(self, *args: object, **kwargs: object) -> _Pipeline:
        self._commands.append(("xadd", args, kwargs))
        return self

    def expire(self, *args: object, **kwargs: object) -> _Pipeline:
        self._commands.append(("expire", args, kwargs))
        return self

    async def execute(self) -> None:
        for name, args, kwargs in self._commands:
            await getattr(self._redis, name)(*args, **kwargs)


class _TimeoutRedis(_Redis):
    def pipeline(self, *, transaction: bool) -> _TimeoutPipeline:
        self.pipeline_transactions.append(transaction)
        return _TimeoutPipeline(self)


class _TimeoutPipeline(_Pipeline):
    async def execute(self) -> None:
        raise RedisTimeoutError("publish timed out")


async def _source(frame: str) -> AsyncIterator[str]:
    yield frame


async def _frames(*frames: str) -> AsyncIterator[str]:
    for frame in frames:
        yield frame


def test_candidate_frame_detection_supports_stored_and_inline_sse() -> None:
    assert _is_assistant_candidate_frame(
        "id: 2-0\nevent: assistant_candidate_delta\ndata: {}\n\n"
    )
    assert _is_assistant_candidate_frame(
        "event: assistant_candidate_reset\ndata: {}\n\n"
    )
    assert not _is_assistant_candidate_frame(
        "id: 3-0\nevent: assistant_item_delta\ndata: {}\n\n"
    )


@pytest.mark.asyncio
async def test_event_store_publishes_a_bounded_ttl_replay_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_id = uuid4()
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    monkeypatch.setattr(store, "_client", lambda *, socket_timeout: redis)
    frame = "event: start\ndata: {}\n\n"

    published = [
        item
        async for item in store.publish(response_id=response_id, source=_source(frame))
    ]

    assert published == [frame]
    key, fields, maxlen, approximate = redis.added[0]
    assert key.endswith(str(response_id))
    assert fields == {"sse": frame}
    assert maxlen == 10_000
    assert approximate is True
    assert redis.expirations == [(key, 24 * 60 * 60)]
    assert redis.closed is True


@pytest.mark.asyncio
async def test_event_store_refreshes_ttl_only_for_first_and_terminal_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_id = uuid4()
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    metric = MagicMock()
    monkeypatch.setattr(store, "_client", lambda *, socket_timeout: redis)
    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.event_store.record_histogram",
        metric,
    )

    published = [
        item
        async for item in store.publish(
            response_id=response_id,
            source=_frames(
                "event: start\ndata: {}\n\n",
                "event: assistant_item_delta\ndata: {}\n\n",
                "event: complete\ndata: {}\n\n",
            ),
        )
    ]

    assert len(published) == 3
    assert len(redis.added) == 3
    assert len(redis.expirations) == 2
    assert redis.pipeline_transactions == [True, True]
    assert [call.kwargs["attributes"] for call in metric.call_args_list] == [
        {"frame_kind": "start"},
        {"frame_kind": "assistant_item_delta"},
        {"frame_kind": "complete"},
    ]


@pytest.mark.asyncio
async def test_event_store_periodically_refreshes_ttl_for_a_long_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    monkeypatch.setattr(store, "_client", lambda *, socket_timeout: redis)
    monkeypatch.setattr(event_store, "_TTL_REFRESH_INTERVAL_SECONDS", 0)

    _ = [
        frame
        async for frame in store.publish(
            response_id=uuid4(),
            source=_frames(
                "event: start\ndata: {}\n\n",
                "event: assistant_item_delta\ndata: {}\n\n",
            ),
        )
    ]

    assert len(redis.expirations) == 2
    assert redis.pipeline_transactions == [True, True]


@pytest.mark.asyncio
async def test_event_store_resumes_after_the_last_seen_sse_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_id = uuid4()
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    monkeypatch.setattr(store, "_client", lambda *, socket_timeout: redis)
    subscription = store.subscribe(response_id=response_id, after="1-0")

    frame = await anext(subscription)
    await subscription.aclose()

    assert frame == "id: 2-0\nevent: complete\ndata: {}\n\n"
    assert next(iter(redis.reads[0][0].values())) == "1-0"
    assert redis.closed is True


@pytest.mark.asyncio
async def test_publish_uses_a_short_timeout_and_never_holds_the_source_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _TimeoutRedis()
    factory = MagicMock(return_value=redis)
    monkeypatch.setattr(event_store.Redis, "from_url", factory)
    frames = (
        "event: start\ndata: {}\n\n",
        "event: assistant_item_delta\ndata: {}\n\n",
    )

    published = [
        frame
        async for frame in ConversationEventStore("redis://example.invalid").publish(
            response_id=uuid4(), source=_frames(*frames)
        )
    ]

    assert published == list(frames)
    assert factory.call_args.kwargs["socket_timeout"] == 1.0
    assert redis.pipeline_transactions == [True]
    assert redis.closed is True


@pytest.mark.asyncio
async def test_subscribe_keeps_a_timeout_above_the_blocking_read_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    factory = MagicMock(return_value=redis)
    monkeypatch.setattr(event_store.Redis, "from_url", factory)
    subscription = ConversationEventStore("redis://example.invalid").subscribe(
        response_id=uuid4(),
        after=None,
    )

    await anext(subscription)
    await subscription.aclose()

    socket_timeout = factory.call_args.kwargs["socket_timeout"]
    assert socket_timeout == 20.0
    assert socket_timeout > event_store._BLOCK_MILLISECONDS / 1_000
