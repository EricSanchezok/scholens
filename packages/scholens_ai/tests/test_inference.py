"""Real Unix-socket proofs for priority, deadlines, isolation and bounds."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import threading

import pytest

from scholens_ai.inference import InferenceServer
from scholens_ai.inference_client import EmbeddingUnavailable, SocketTextEmbedder
from scholens_ai.inference_protocol import FRAME_HEADER, MAX_FRAME_BYTES


class Model:
    revision = "test-revision"

    def __init__(self, *, blocking=False):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        if not blocking:
            self.release.set()
        self.active = 0
        self.peak = 0

    def _embed(self, texts, kind):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.calls.append((kind, tuple(texts)))
            self.started.set()
            assert self.release.wait(3)
            return [[float(i == len(text) % 384) for i in range(384)] for text in texts]
        finally:
            self.active -= 1

    def embed_query(self, text):
        return self._embed([text], "query")[0]

    def embed_passages(self, texts):
        return self._embed(texts, "passage")


@asynccontextmanager
async def running(model, **kwargs):
    # Keep paths below Darwin's Unix-socket length bound.
    with tempfile.TemporaryDirectory(prefix="si-", dir="/tmp") as directory:
        path = str(Path(directory) / "model.sock")
        service = InferenceServer(model, **kwargs)
        server = await asyncio.start_unix_server(service.handle, path=path)
        scheduler = asyncio.create_task(service.run())
        try:
            async with server:
                yield path, service
        finally:
            model.release.set()
            service.stop()
            await scheduler
            server.close()
            await server.wait_closed()


def test_client_uses_exact_revision_and_validates_vectors_without_loading_a_model():
    async def scenario():
        model = Model()
        async with running(model) as (path, _service):
            client = SocketTextEmbedder(path, revision=model.revision)
            await asyncio.to_thread(client.health)
            vector = await asyncio.to_thread(client.embed_query, "example")
            assert len(vector) == 384 and sum(vector) == 1
            wrong = SocketTextEmbedder(path, revision="other")
            with pytest.raises(EmbeddingUnavailable, match="revision"):
                await asyncio.to_thread(wrong.embed_query, "do not infer")
        assert model.calls == [("query", ("example",))]

    asyncio.run(scenario())


def test_query_overtakes_index_microbatches_and_only_one_model_call_runs():
    async def scenario():
        model = Model(blocking=True)
        async with running(model) as (path, service):
            client = SocketTextEmbedder(path, revision=model.revision, query_timeout=2)
            passages = asyncio.create_task(
                asyncio.to_thread(client.embed_passages, ["a"] * 8)
            )
            assert await asyncio.to_thread(model.started.wait, 1)
            query = asyncio.create_task(asyncio.to_thread(client.embed_query, "urgent"))
            async with asyncio.timeout(1):
                while not service._queries:
                    await asyncio.sleep(0.001)
            model.release.set()
            assert len(await query) == 384
            assert len(await passages) == 8
        assert model.peak == 1
        assert model.calls[0][0] == "passage"
        assert model.calls[1] == ("query", ("urgent",))
        assert all(len(texts) == 1 for _kind, texts in model.calls)

    asyncio.run(scenario())


def test_timed_out_client_drops_queued_work_and_never_starts_local_fallback():
    async def scenario():
        model = Model(blocking=True)
        async with running(model) as (path, _service):
            client = SocketTextEmbedder(
                path, revision=model.revision, query_timeout=0.05
            )
            passages = asyncio.create_task(
                asyncio.to_thread(client.embed_passages, ["held"])
            )
            assert await asyncio.to_thread(model.started.wait, 1)
            with pytest.raises(EmbeddingUnavailable):
                await asyncio.to_thread(client.embed_query, "expired")
            model.release.set()
            await passages
        assert all(kind != "query" for kind, _texts in model.calls)

    asyncio.run(scenario())


def test_query_burst_gives_waiting_index_work_a_bounded_turn():
    async def scenario():
        # All fourteen socket clients must reach the server before releasing
        # the model barrier. A small CI host's default executor has fewer
        # threads and deadlocks the test harness before it can test fairness.
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=16)
        )
        model = Model(blocking=True)
        async with running(model) as (path, service):
            client = SocketTextEmbedder(path, revision=model.revision, query_timeout=2)
            first = asyncio.create_task(asyncio.to_thread(client.embed_query, "first"))
            assert await asyncio.to_thread(model.started.wait, 1)
            queries = [
                asyncio.create_task(asyncio.to_thread(client.embed_query, f"query-{i}"))
                for i in range(12)
            ]
            index = asyncio.create_task(
                asyncio.to_thread(client.embed_passages, ["index"])
            )
            async with asyncio.timeout(1):
                while len(service._queries) != 12 or not service._passages:
                    await asyncio.sleep(0.001)
            model.release.set()
            await asyncio.gather(first, index, *queries)
        index_position = next(
            i for i, (kind, _) in enumerate(model.calls) if kind == "passage"
        )
        assert index_position <= 8
        assert model.peak == 1

    asyncio.run(scenario())


def test_oversize_wire_header_is_rejected_before_reading_the_body():
    async def scenario():
        model = Model()
        async with running(model) as (path, _service):
            reader, writer = await asyncio.open_unix_connection(path)
            writer.write(FRAME_HEADER.pack(MAX_FRAME_BYTES + 1))
            await writer.drain()
            assert await asyncio.wait_for(reader.read(1), 1) == b""
            writer.close()
            await writer.wait_closed()
        assert model.calls == []

    asyncio.run(scenario())


def test_full_host_queue_rejects_more_clients_with_bounded_latency():
    async def scenario():
        model = Model(blocking=True)
        async with running(model, max_connections=1) as (path, _service):
            client = SocketTextEmbedder(path, revision=model.revision)
            first = asyncio.create_task(
                asyncio.to_thread(client.embed_passages, ["held"])
            )
            assert await asyncio.to_thread(model.started.wait, 1)
            with pytest.raises(EmbeddingUnavailable):
                await asyncio.wait_for(
                    asyncio.to_thread(client.embed_query, "excess"), 1
                )
            model.release.set()
            await first
        assert len(model.calls) == 1

    asyncio.run(scenario())


def test_socket_configuration_does_not_construct_local_model_on_failure(monkeypatch):
    from scholens_ai import embeddings

    monkeypatch.setenv(
        "SCHOLENS_EMBEDDING_SOCKET", "/tmp/nonexistent-scholens-test.sock"
    )
    monkeypatch.setattr(
        embeddings, "try_local_embedder", lambda: pytest.fail("local model fallback")
    )
    embeddings.configured_embedder.cache_clear()
    try:
        with pytest.raises(EmbeddingUnavailable):
            embeddings.embed_text("query", kind="query")
    finally:
        embeddings.configured_embedder.cache_clear()
