"""Own async network lifetimes, including retries and streaming bodies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from aiobotocore.config import AioConfig  # type: ignore[import-untyped]
from aiobotocore.session import get_session  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class AsyncS3Storage:
    bucket: str
    region: str
    addressing_style: Literal["auto", "virtual", "path"] = "virtual"
    endpoint_url: str | None = None

    def _client(self) -> Any:
        if not self.bucket:
            raise ValueError("s3_bucket_required")
        return get_session().create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            config=AioConfig(
                signature_version="s3v4",
                s3={"addressing_style": self.addressing_style},
                connect_timeout=5,
                read_timeout=10,
                retries={"mode": "standard", "total_max_attempts": 2},
                max_pool_connections=1,
            ),
        )

    async def read(
        self,
        key: str,
        *,
        max_bytes: int,
        timeout: float = 45,
        etag: str | None = None,
        version_id: str | None = None,
    ) -> bytes:
        if max_bytes < 1 or timeout <= 0:
            raise ValueError("s3_object_byte_bound_invalid")
        request: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if etag is not None:
            request["IfMatch"] = etag
        if version_id is not None:
            request["VersionId"] = version_id
        # Timeout owns connection setup, credentials, retries and body, rather
        # than only an executor Future that cannot interrupt a blocking socket.
        async with asyncio.timeout(timeout), self._client() as client:
            response = await client.get_object(**request)
            async with response["Body"] as body:
                if response.get("ContentLength", 0) > max_bytes:
                    raise ValueError("s3_object_byte_bound_exceeded")
                data = bytearray()
                while chunk := await body.read(
                    min(64 * 1024, max_bytes + 1 - len(data))
                ):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("s3_object_byte_bound_exceeded")
                return bytes(data)

    async def download(
        self, key: str, destination: Path, *, max_bytes: int, timeout: float = 180
    ) -> int:
        if max_bytes < 1 or timeout <= 0:
            raise ValueError("s3_object_byte_bound_invalid")
        written = 0
        try:
            async with asyncio.timeout(timeout), self._client() as client:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as body:
                    if response.get("ContentLength", 0) > max_bytes:
                        raise ValueError("s3_object_byte_bound_exceeded")
                    with destination.open("wb") as output:
                        while chunk := await body.read(64 * 1024):
                            written += len(chunk)
                            if written > max_bytes:
                                raise ValueError("s3_object_byte_bound_exceeded")
                            output.write(chunk)
            return written
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    async def delete_prefix_pages(
        self, prefixes: tuple[str, ...], *, timeout: float = 45
    ) -> bool:
        if (
            not prefixes
            or len(prefixes) > 2
            or any(not p or not p.endswith("/") for p in prefixes)
        ):
            raise ValueError("s3_cleanup_prefix_invalid")
        remaining = False
        async with asyncio.timeout(timeout), self._client() as client:
            for prefix in prefixes:
                page = await client.list_objects_v2(
                    Bucket=self.bucket, Prefix=prefix, MaxKeys=100
                )
                keys = [entry["Key"] for entry in page.get("Contents", [])]
                if len(keys) > 100 or any(not key.startswith(prefix) for key in keys):
                    raise ValueError("s3_cleanup_namespace_mismatch")
                if keys:
                    result = await client.delete_objects(
                        Bucket=self.bucket,
                        Delete={
                            "Objects": [{"Key": key} for key in keys],
                            "Quiet": True,
                        },
                    )
                    if result.get("Errors"):
                        raise RuntimeError("s3_cleanup_deletion_failed")
                remaining = remaining or bool(page.get("IsTruncated"))
        return not remaining
