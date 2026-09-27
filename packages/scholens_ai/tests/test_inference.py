"""Real Unix-socket proofs for priority, deadlines, isolation and bounds."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import threading
import time
import subprocess
import sys
import json

import pytest

from scholens_ai.inference import InferenceServer
from scholens_ai.inference_client import EmbeddingUnavailable, SocketTextEmbedder
from scholens_ai.inference_protocol import FRAME_HEADER, MAX_FRAME_BYTES
from scholens_ai.inference_health import check_health


@pytest.mark.parametrize("matching_revision", [True, False])
def test_health_command_checks_readiness_without_model_or_provider_imports(
    matching_revision,
):
    from scholens_ai import EMBEDDING_MODEL_REVISION

    async def scenario():
        model = Model()
        model.revision = EMBEDDING_MODEL_REVISION if matching_revision else "other"
        async with running(model) as (path, _service):
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", _LIGHTWEIGHT_HEALTH_COMMAND, path],
                capture_output=True,
                text=True,
                timeout=10,
            )
        assert "Health probe imported" not in result.stderr, result.stderr
        assert result.returncode == (0 if matching_revision else 1), result.stderr
        if not matching_revision:
            assert "inference_revision" in result.stderr
        assert model.calls == []

    asyncio.run(scenario())


def test_health_command_rejects_missing_owner_without_loading_a_model():
    with tempfile.TemporaryDirectory(prefix="si-", dir="/tmp") as directory:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _LIGHTWEIGHT_HEALTH_COMMAND,
                f"{directory}/missing.sock",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert result.returncode == 1
    assert "Health probe imported" not in result.stderr, result.stderr
    assert "inference_unavailable" in result.stderr


_LIGHTWEIGHT_HEALTH_COMMAND = """
import importlib.abc
import runpy
import sys

class NoModelOrProvider(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'tokenizers', 'onnxruntime', 'pydantic', 'pydantic_ai', 'openai', 'httpx', 'boto3'}:
            raise AssertionError(f'Health probe imported {fullname}')

sys.meta_path.insert(0, NoModelOrProvider())
sys.argv = ['scholens_ai.inference', '--check', '--socket', sys.argv[1]]
runpy.run_module('scholens_ai.inference', run_name='__main__')
"""


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"model_revision": "test-revision", "unexpected": True},
        {"model_revision": "test-revision", "vectors": [[1.0]]},
        {"model_revision": "test-revision", "error": "stopping"},
        {"model_revision": "test-revision", "vectors": None},
    ],
)
def test_health_rejects_malformed_or_failed_responses(response):
    async def scenario():
        async def handle(reader, writer):
            size = FRAME_HEADER.unpack(await reader.readexactly(FRAME_HEADER.size))[0]
            await reader.readexactly(size)
            body = json.dumps(response).encode()
            writer.write(FRAME_HEADER.pack(len(body)) + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        with tempfile.TemporaryDirectory(prefix="si-", dir="/tmp") as directory:
            path = f"{directory}/model.sock"
            server = await asyncio.start_unix_server(handle, path=path)
            async with server:
                with pytest.raises(EmbeddingUnavailable):
                    await asyncio.to_thread(
                        check_health, path, revision="test-revision"
                    )

    asyncio.run(scenario())


def test_health_deadline_bounds_an_unresponsive_owner():
    async def scenario():
        async def handle(reader, writer):
            await reader.read()
            writer.close()
            await writer.wait_closed()

        with tempfile.TemporaryDirectory(prefix="si-", dir="/tmp") as directory:
            path = f"{directory}/model.sock"
            server = await asyncio.start_unix_server(handle, path=path)
            async with server:
                with pytest.raises(EmbeddingUnavailable):
                    await asyncio.wait_for(
                        asyncio.to_thread(check_health, path, timeout=0.05), 1
                    )

    asyncio.run(scenario())


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


@pytest.mark.parametrize("character", ["界", "🙂", "\x01"])
def test_valid_long_texts_cross_frame_bound_without_truncation_or_reordering(character):
    async def scenario():
        model = Model()
        texts = [character * (24_000 - i) for i in range(8)]
        async with running(model) as (path, _service):
            client = SocketTextEmbedder(path, revision=model.revision)
            vectors = await asyncio.to_thread(client.embed_passages, texts)
        assert [vector.index(1.0) for vector in vectors] == [
            len(text) % 384 for text in texts
        ]
        assert [text for _, batch in model.calls for text in batch] == texts

    asyncio.run(scenario())


def test_split_requests_share_one_deadline_and_cancel_remaining_work():
    class SlowModel(Model):
        def _embed(self, texts, kind):
            result = super()._embed(texts, kind)
            time.sleep(0.04)
            return result

    async def scenario():
        model = SlowModel()
        async with running(model) as (path, _service):
            client = SocketTextEmbedder(
                path, revision=model.revision, passage_timeout=0.13
            )
            with pytest.raises(EmbeddingUnavailable):
                await asyncio.to_thread(client.embed_passages, ["界" * 24_000] * 8)
        assert len(model.calls) < 8

    asyncio.run(scenario())


def test_invalid_request_uses_a_content_free_degradation_signal():
    client = SocketTextEmbedder("/tmp/unused-inference-test.sock")
    with pytest.raises(
        EmbeddingUnavailable, match="inference_request_invalid"
    ) as error:
        client.embed_passages(["private fixture " * 24_000])
    assert error.value.__cause__ is None
    assert "private fixture" not in str(error.value)


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
