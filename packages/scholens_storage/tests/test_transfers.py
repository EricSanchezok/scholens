import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError

from scholens_storage import AsyncS3Storage


@asynccontextmanager
async def object_server(
    *,
    body: bytes = b"abc",
    trickle: bool = False,
    status: int = 200,
    declared_size: bool = True,
) -> AsyncIterator[tuple[str, asyncio.Event]]:
    closed = asyncio.Event()
    handlers: set[asyncio.Task[None]] = set()

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            length = (
                f"Content-Length: {len(body)}\r\n"
                if declared_size
                else "Connection: close\r\n"
            )
            writer.write(f"HTTP/1.1 {status} Fixture\r\n{length}\r\n".encode())
            await writer.drain()
            if trickle:
                for value in body:
                    writer.write(bytes([value]))
                    await writer.drain()
                    await asyncio.sleep(0.025)
            else:
                writer.write(body)
                await writer.drain()
            if declared_size:
                await reader.read()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            closed.set()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", closed
    finally:
        server.close()
        await server.wait_closed()
        for task in handlers.copy():
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)


def storage(endpoint: str) -> AsyncS3Storage:
    return AsyncS3Storage(bucket="fixture", region="us-east-1", endpoint_url=endpoint)


@pytest.fixture(autouse=True)
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fixture")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fixture")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)


@pytest.mark.parametrize("max_bytes", [2, 3])
@pytest.mark.parametrize("declared_size", [True, False])
def test_byte_ceiling_closes_connection(max_bytes: int, declared_size: bool) -> None:
    async def scenario() -> None:
        async with object_server(declared_size=declared_size) as (url, closed):
            if max_bytes == 2:
                with pytest.raises(ValueError, match="byte_bound"):
                    await storage(url).read("key", max_bytes=max_bytes)
            else:
                assert await storage(url).read("key", max_bytes=max_bytes) == b"abc"
            await asyncio.wait_for(closed.wait(), 1)

    asyncio.run(scenario())


def test_absolute_deadline_stops_trickling_body_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with object_server(body=b"a" * 100, trickle=True) as (url, closed):
            started = asyncio.get_running_loop().time()
            destination = tmp_path / "partial.pdf"
            with pytest.raises(TimeoutError):
                await storage(url).download(
                    "key", destination, max_bytes=100, timeout=0.3
                )
            assert asyncio.get_running_loop().time() - started < 1
            assert not destination.exists()
            await asyncio.wait_for(closed.wait(), 1)

    asyncio.run(scenario())


def test_cancellation_closes_inflight_transfer_before_returning() -> None:
    async def scenario() -> None:
        async with object_server(body=b"a" * 100, trickle=True) as (url, closed):
            task = asyncio.create_task(storage(url).read("key", max_bytes=100))
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(closed.wait(), 1)

    asyncio.run(scenario())


def test_missing_object_preserves_sdk_error_code() -> None:
    async def scenario() -> None:
        body = b"<Error><Code>NoSuchKey</Code><Message>missing</Message></Error>"
        async with object_server(body=body, status=404) as (url, _):
            with pytest.raises(ClientError) as error:
                await storage(url).read("key", max_bytes=100)
            assert error.value.response["Error"]["Code"] == "NoSuchKey"

    asyncio.run(scenario())


def test_cleanup_is_one_bounded_page_per_prefix_and_rejects_foreign_keys() -> None:
    async def scenario() -> None:
        client = AsyncMock()
        client.list_objects_v2.side_effect = [
            {"Contents": [{"Key": "owned/1"}], "IsTruncated": True},
            {"Contents": [{"Key": "other/1"}]},
        ]
        client.delete_objects.return_value = {}
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("scholens_storage.transfers.get_session") as session:
            session.return_value.create_client.return_value = context
            service = storage("http://127.0.0.1")
            assert not await service.delete_prefix_pages(("owned/", "other/"))
            assert [
                c.kwargs["MaxKeys"] for c in client.list_objects_v2.call_args_list
            ] == [100, 100]
            client.list_objects_v2.side_effect = [{"Contents": [{"Key": "foreign/1"}]}]
            client.delete_objects.reset_mock()
            with pytest.raises(ValueError, match="namespace_mismatch"):
                await service.delete_prefix_pages(("owned/",))
            client.delete_objects.assert_not_awaited()

    asyncio.run(scenario())
