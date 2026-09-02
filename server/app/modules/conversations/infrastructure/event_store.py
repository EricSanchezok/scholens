"""Bounded Redis replay log for detachable Conversation subscribers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from time import monotonic
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from scholens_observability import add_counter, log_event, record_histogram

logger = logging.getLogger(__name__)

_MAX_EVENTS = 10_000
_TERMINAL_TTL_SECONDS = 24 * 60 * 60
_TTL_REFRESH_INTERVAL_SECONDS = _TERMINAL_TTL_SECONDS // 2
_BLOCK_MILLISECONDS = 15_000
_PUBLISH_SOCKET_TIMEOUT_SECONDS = 1.0
_SUBSCRIBE_SOCKET_TIMEOUT_SECONDS = 20.0
_PERSISTENCE_QUEUE_MAX_BYTES = 512 * 1024
_PERSISTENCE_FLUSH_INTERVAL_SECONDS = 0.1
_TERMINAL_EVENT_KINDS = frozenset({"complete", "cancelled", "error"})
_EVENT_KINDS = frozenset(
    {
        "start",
        "assistant_item_start",
        "assistant_item_delta",
        "assistant_item_complete",
        "assistant_candidate_start",
        "assistant_candidate_delta",
        "assistant_candidate_reset",
        "activity",
        "references",
        "response_ready",
        "suggestions",
        "phase",
        *_TERMINAL_EVENT_KINDS,
    }
)


def _key(response_id: UUID) -> str:
    return f"scholens:conversation-events:{response_id}"


def _frame_kind(frame: str) -> str:
    if frame.startswith(":"):
        return "comment"
    for line in frame.splitlines():
        if line.startswith("event: "):
            candidate = line.removeprefix("event: ")
            return candidate if candidate in _EVENT_KINDS else "unknown"
    return "unknown"


class ConversationEventStore:
    """Publish and replay sanitized SSE frames without making Redis canonical."""

    def __init__(self, redis_url: str | None) -> None:
        self._redis_url = redis_url

    def _client(self, *, socket_timeout: float) -> Redis | None:
        if self._redis_url is None:
            return None
        return Redis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=socket_timeout,
            retry_on_timeout=False,
        )

    async def publish(
        self,
        *,
        response_id: UUID,
        source: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Persist each frame best-effort while preserving the source stream."""
        client = self._client(socket_timeout=_PUBLISH_SOCKET_TIMEOUT_SECONDS)
        first_frame = True
        ttl_refresh_due_at: float | None = None
        try:
            async for frame in source:
                if client is not None:
                    frame_kind = _frame_kind(frame)
                    append_started = monotonic()
                    try:
                        key = _key(response_id)
                        refresh_ttl = (
                            first_frame
                            or frame_kind in _TERMINAL_EVENT_KINDS
                            or (
                                ttl_refresh_due_at is not None
                                and append_started >= ttl_refresh_due_at
                            )
                        )
                        if refresh_ttl:
                            pipeline = client.pipeline(transaction=True)
                            pipeline.xadd(
                                key,
                                {"sse": frame},
                                maxlen=_MAX_EVENTS,
                                approximate=True,
                            )
                            pipeline.expire(key, _TERMINAL_TTL_SECONDS)
                            await pipeline.execute()
                            ttl_refresh_due_at = (
                                append_started + _TTL_REFRESH_INTERVAL_SECONDS
                            )
                        else:
                            await client.xadd(
                                key,
                                {"sse": frame},
                                maxlen=_MAX_EVENTS,
                                approximate=True,
                            )
                        record_histogram(
                            "scholens.conversation.event_store.append_latency",
                            (monotonic() - append_started) * 1000,
                            attributes={"frame_kind": frame_kind},
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
                first_frame = False
                yield frame
        finally:
            if client is not None:
                await client.aclose()

    async def publish_nonblocking(
        self,
        *,
        response_id: UUID,
        source: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Stream frames immediately while persisting them on a bounded sink.

        The worker used to await every Redis ``XADD`` before yielding the next
        model frame.  That made a slow cache connection indistinguishable from
        a slow model.  This path keeps the source hot and gives persistence its
        own bounded queue. Lifecycle and terminal frames are always flushed in
        order. UI-side text coalescing remains the responsibility of the Web
        live store, so persistence never waits for a later source frame.
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=256)
        pending_bytes = 0

        async def writer() -> None:
            nonlocal pending_bytes
            client = self._client(socket_timeout=_PUBLISH_SOCKET_TIMEOUT_SECONDS)
            if client is None:
                while await queue.get() is not None:
                    pass
                return
            first_frame = True
            ttl_refresh_due_at: float | None = None
            try:
                while True:
                    frame = await queue.get()
                    if frame is None:
                        return
                    pending_bytes = max(0, pending_bytes - len(frame.encode("utf-8")))
                    frame_kind = _frame_kind(frame)
                    append_started = monotonic()
                    try:
                        key = _key(response_id)
                        refresh_ttl = (
                            first_frame
                            or frame_kind in _TERMINAL_EVENT_KINDS
                            or (
                                ttl_refresh_due_at is not None
                                and append_started >= ttl_refresh_due_at
                            )
                        )
                        if refresh_ttl:
                            pipeline = client.pipeline(transaction=True)
                            pipeline.xadd(
                                key,
                                {"sse": frame},
                                maxlen=_MAX_EVENTS,
                                approximate=True,
                            )
                            pipeline.expire(key, _TERMINAL_TTL_SECONDS)
                            await pipeline.execute()
                            ttl_refresh_due_at = (
                                append_started + _TTL_REFRESH_INTERVAL_SECONDS
                            )
                        else:
                            await client.xadd(
                                key,
                                {"sse": frame},
                                maxlen=_MAX_EVENTS,
                                approximate=True,
                            )
                        record_histogram(
                            "scholens.conversation.event_store.append_latency",
                            (monotonic() - append_started) * 1000,
                            attributes={"frame_kind": frame_kind},
                        )
                    except RedisError as error:
                        add_counter(
                            "scholens.conversation.event_store_failures",
                            attributes={"operation": "publish_nonblocking"},
                        )
                        log_event(
                            logger,
                            logging.WARNING,
                            "conversation.events.publish_nonblocking_failed",
                            exc_info=error,
                            response_id=str(response_id),
                        )
                        return
                    first_frame = False
            finally:
                await client.aclose()

        writer_task = asyncio.create_task(
            writer(), name=f"conversation-event-persist:{response_id}"
        )

        async def enqueue(frame: str) -> None:
            nonlocal pending_bytes
            if writer_task.done():
                return
            encoded_bytes = len(frame.encode("utf-8"))
            while (
                pending_bytes + encoded_bytes > _PERSISTENCE_QUEUE_MAX_BYTES
                and _frame_kind(frame) not in _TERMINAL_EVENT_KINDS
            ):
                if writer_task.done():
                    return
                await asyncio.sleep(_PERSISTENCE_FLUSH_INTERVAL_SECONDS)
            if writer_task.done():
                return
            await queue.put(frame)
            pending_bytes += encoded_bytes

        try:
            async for frame in source:
                await enqueue(frame)
                yield frame
            if not writer_task.done():
                await queue.put(None)
                await writer_task
        finally:
            if not writer_task.done():
                await queue.put(None)
                await asyncio.gather(writer_task, return_exceptions=True)

    async def append_terminal(self, *, response_id: UUID, frame: str) -> None:
        """Best-effort append of one terminal frame with a refreshed replay TTL."""
        if _frame_kind(frame) not in _TERMINAL_EVENT_KINDS:
            raise ValueError("Conversation terminal append requires a terminal event")

        async def source() -> AsyncIterator[str]:
            yield frame

        async for _frame in self.publish(response_id=response_id, source=source()):
            pass

    async def subscribe(
        self,
        *,
        response_id: UUID,
        after: str | None,
    ) -> AsyncIterator[str | None]:
        """Yield framed replay events; ``None`` represents an SSE heartbeat."""
        client = self._client(socket_timeout=_SUBSCRIBE_SOCKET_TIMEOUT_SECONDS)
        if client is None:
            yield None
            return
        cursor = after or "0-0"
        try:
            while True:
                rows = await client.xread(
                    {_key(response_id): cursor},
                    count=1,
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
