from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.modules.conversations.infrastructure.event_store import (
    ConversationEventStore,
)


class _Redis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, str], int, bool]] = []
        self.expirations: list[tuple[str, int]] = []
        self.reads: list[tuple[dict[str, str], int, int]] = []
        self.closed = False

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


async def _source(frame: str) -> AsyncIterator[str]:
    yield frame


@pytest.mark.asyncio
async def test_event_store_publishes_a_bounded_ttl_replay_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_id = uuid4()
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    monkeypatch.setattr(store, "_client", lambda: redis)
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
async def test_event_store_resumes_after_the_last_seen_sse_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_id = uuid4()
    redis = _Redis()
    store = ConversationEventStore("redis://example.invalid")
    monkeypatch.setattr(store, "_client", lambda: redis)
    subscription = store.subscribe(response_id=response_id, after="1-0")

    frame = await anext(subscription)
    await subscription.aclose()

    assert frame == "id: 2-0\nevent: complete\ndata: {}\n\n"
    assert next(iter(redis.reads[0][0].values())) == "1-0"
    assert redis.closed is True
