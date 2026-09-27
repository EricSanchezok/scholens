"""Single-model host process with query priority and bounded index microbatches."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
from typing import Literal

from scholens_ai.embeddings import LocalOnnxTextEmbedder, TextEmbedder
from scholens_ai.inference_client import SocketTextEmbedder
from scholens_ai.inference_protocol import (
    FRAME_HEADER,
    MAX_FRAME_BYTES,
    InferenceRequest,
    InferenceResponse,
    frame,
)

MAX_CONNECTIONS = 64
INDEX_MICROBATCH = 1
QUERY_BURST = 8
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Work:
    request: InferenceRequest
    deadline: float
    future: asyncio.Future[InferenceResponse]
    vectors: list[list[float]] = field(default_factory=list)


class InferenceServer:
    def __init__(
        self, embedder: TextEmbedder, *, max_connections: int = MAX_CONNECTIONS
    ) -> None:
        if not 1 <= max_connections <= MAX_CONNECTIONS:
            raise ValueError("Invalid inference connection bound")
        self._embedder = embedder
        self._limit = max_connections
        self._connections = 0
        self._queries: deque[_Work] = deque()
        self._passages: deque[_Work] = deque()
        self._wakeup = asyncio.Event()
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True
        self._wakeup.set()

    def _error(
        self,
        code: Literal[
            "busy", "deadline", "revision", "invalid", "inference", "stopping"
        ],
    ) -> InferenceResponse:
        return InferenceResponse(model_revision=self._embedder.revision, error=code)

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self._connections >= self._limit or self._stopping:
            writer.close()
            await writer.wait_closed()
            return
        self._connections += 1
        started = asyncio.get_running_loop().time()
        future: asyncio.Future[InferenceResponse] | None = None
        disconnected: asyncio.Task[bytes] | None = None
        try:
            async with asyncio.timeout(5):
                size = FRAME_HEADER.unpack(await reader.readexactly(FRAME_HEADER.size))[
                    0
                ]
                if not 0 < size <= MAX_FRAME_BYTES:
                    raise ValueError("Inference request bound")
                request = InferenceRequest.model_validate_json(
                    await reader.readexactly(size)
                )
            if request.model_revision != self._embedder.revision:
                response = self._error("revision")
            elif request.kind == "health":
                response = InferenceResponse(model_revision=self._embedder.revision)
            elif len(self._queries) + len(self._passages) >= self._limit:
                response = self._error("busy")
            else:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                work = _Work(request, loop.time() + request.deadline_ms / 1000, future)
                (self._queries if request.kind == "query" else self._passages).append(
                    work
                )
                self._wakeup.set()
                # A client that falls back or cancels relinquishes queued work.
                disconnected = asyncio.create_task(reader.read(1))
                done, _pending = await asyncio.wait(
                    (future, disconnected),
                    timeout=request.deadline_ms / 1000,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnected in done:
                    return
                response = (
                    future.result() if future in done else self._error("deadline")
                )
            writer.write(frame(response.model_dump_json().encode()))
            async with asyncio.timeout(1):
                await writer.drain()
            logger.info(
                json.dumps(
                    {
                        "event": "inference.request.completed",
                        "kind": request.kind,
                        "model_revision": self._embedder.revision,
                        "status": response.error or "success",
                        "text_count": len(request.texts),
                        "duration_ms": round(
                            (asyncio.get_running_loop().time() - started) * 1000, 2
                        ),
                        "queue_depth": len(self._queries) + len(self._passages),
                    }
                )
            )
        except (OSError, ValueError, asyncio.IncompleteReadError, TimeoutError):
            # Never log request bytes or model input on protocol failures.
            pass
        finally:
            if future is not None and not future.done():
                future.cancel()
            if disconnected is not None:
                disconnected.cancel()
                await asyncio.gather(disconnected, return_exceptions=True)
            self._connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        streak = 0
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference") as pool:
            while not self._stopping:
                if not self._queries and not self._passages:
                    self._wakeup.clear()
                    await self._wakeup.wait()
                    continue
                use_query = bool(self._queries) and (
                    streak < QUERY_BURST or not self._passages
                )
                work = (self._queries if use_query else self._passages).popleft()
                if work.future.done():
                    continue
                if loop.time() >= work.deadline:
                    work.future.set_result(self._error("deadline"))
                    continue
                streak = streak + 1 if use_query else 0
                texts = work.request.texts[
                    len(work.vectors) : len(work.vectors) + INDEX_MICROBATCH
                ]
                try:
                    if use_query:
                        vector = await loop.run_in_executor(
                            pool, self._embedder.embed_query, texts[0]
                        )
                        vectors = [vector]
                    else:
                        vectors = await loop.run_in_executor(
                            pool, self._embedder.embed_passages, texts
                        )
                    # Validate each microbatch before retaining it.
                    InferenceResponse(
                        model_revision=self._embedder.revision, vectors=vectors
                    )
                    if len(vectors) != len(texts):
                        raise ValueError("Inference vector count")
                    work.vectors.extend(vectors)
                    if work.future.done():
                        continue
                    if len(work.vectors) == len(work.request.texts):
                        work.future.set_result(
                            InferenceResponse(
                                model_revision=self._embedder.revision,
                                vectors=work.vectors,
                            )
                        )
                    else:
                        self._passages.append(work)
                except Exception:
                    if not work.future.done():
                        work.future.set_result(self._error("inference"))
            for work in (*self._queries, *self._passages):
                if not work.future.done():
                    work.future.set_result(self._error("stopping"))


async def serve(path: Path) -> None:
    # The lock is acquired before model initialization: overlapping deployment
    # cannot create a second model owner or unlink an active owner's socket.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model = LocalOnnxTextEmbedder()
        await asyncio.to_thread(model.embed_query, "inference warmup")
        scheduler = InferenceServer(model)
        server = await asyncio.start_unix_server(
            scheduler.handle, path=path, limit=MAX_FRAME_BYTES
        )
        os.chmod(path, 0o660)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, scheduler.stop)
        async with server:
            try:
                await scheduler.run()
            finally:
                server.close()
                await server.wait_closed()
                path.unlink(missing_ok=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--socket", type=Path, default=os.getenv("SCHOLENS_EMBEDDING_SOCKET")
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.socket is None:
        parser.error("--socket is required")
    if args.check:
        SocketTextEmbedder(str(args.socket)).health()
    else:
        asyncio.run(serve(args.socket))


if __name__ == "__main__":
    main()
