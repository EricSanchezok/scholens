"""Bounded Redis replay log for detachable Conversation subscribers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from scholens_observability import add_counter, log_event

logger = logging.getLogger(__name__)

_MAX_EVENTS = 10_000
_TERMINAL_TTL_SECONDS = 24 * 60 * 60
_BLOCK_MILLISECONDS = 15_000


def _key(response_id: UUID) -> str:
    return f"scholens:conversation-events:{response_id}"


class ConversationEventStore:
    """Publish and replay sanitized SSE frames without making Redis canonical."""

    def __init__(self, redis_url: str | None) -> None:
        self._redis_url = redis_url

    def _client(self) -> Redis | None:
        if self._redis_url is None:
            return None
        return Redis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=20,
            retry_on_timeout=False,
        )

    async def publish(
        self,
        *,
        response_id: UUID,
        source: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Persist each frame best-effort while preserving the source stream."""
        client = self._client()
        try:
            async for frame in source:
                if client is not None:
                    try:
                        await client.xadd(
                            _key(response_id),
                            {"sse": frame},
                            maxlen=_MAX_EVENTS,
                            approximate=True,
                        )
                        await client.expire(
                            _key(response_id),
                            _TERMINAL_TTL_SECONDS,
                        )
                    except RedisError as error:
                        add_counter(
                            "scholens.conversation.event_store_failures",
                            attributes={"operation": "publish"},
                        )
                        log_event(
                            logger,
                            logging.WARNING,
                            "conversation.events.publish_failed",
                            exc_info=error,
                            response_id=str(response_id),
                        )
                        await client.aclose()
                        client = None
                yield frame
        finally:
            if client is not None:
                await client.aclose()

    async def subscribe(
        self,
        *,
        response_id: UUID,
        after: str | None,
    ) -> AsyncIterator[str | None]:
        """Yield framed replay events; ``None`` represents an SSE heartbeat."""
        client = self._client()
        if client is None:
            yield None
            return
        cursor = after or "0-0"
        try:
            while True:
                rows = await client.xread(
                    {_key(response_id): cursor},
                    count=100,
                    block=_BLOCK_MILLISECONDS,
                )
                if not rows:
                    yield None
                    continue
                typed_rows = cast(
                    list[tuple[str, list[tuple[str, dict[str, str]]]]],
                    rows,
                )
                for _stream, events in typed_rows:
                    for event_id, fields in events:
                        cursor = str(event_id)
                        frame = fields.get("sse")
                        if isinstance(frame, str):
                            yield f"id: {cursor}\n{frame}"
        except RedisError as error:
            add_counter(
                "scholens.conversation.event_store_failures",
                attributes={"operation": "subscribe"},
            )
            log_event(
                logger,
                logging.WARNING,
                "conversation.events.subscribe_failed",
                exc_info=error,
                response_id=str(response_id),
            )
            yield None
        finally:
            await client.aclose()


__all__ = ["ConversationEventStore"]
