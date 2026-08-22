"""sanchezcloud-identity adapter for read-only shared avatars."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal, cast

import boto3
from botocore.config import Config
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sanchezcloud_identity.avatar_manager import AvatarManager
from sanchezcloud_identity.avatar_s3 import S3AvatarStorage
from sanchezcloud_identity.db.avatar_asyncpg import AsyncpgAvatarDatabase
from sanchezcloud_identity.exceptions import (
    AvatarNotFoundError,
    AvatarStorageError,
    DBError,
)
from scholens_observability import add_counter

from app.modules.identity.application import (
    SharedAvatarNotFoundError,
    SharedAvatarReader,
    SharedAvatarUnavailableError,
)
from app.modules.identity.infrastructure.sanchezcloud_identity import get_auth_pool
from app.shared.application import AvatarReference

logger = logging.getLogger(__name__)
_CACHE_MISS = object()


def _failure_stage(
    exc: Exception,
) -> Literal["avatar_storage", "identity_adapter", "identity_database"]:
    if isinstance(exc, DBError):
        return "identity_database"
    if isinstance(exc, AvatarStorageError):
        return "avatar_storage"
    return "identity_adapter"


@dataclass(frozen=True, slots=True)
class _AvatarCacheEntry:
    avatar: AvatarReference | None
    valid_until: datetime


class SharedAvatarSettings(BaseSettings):
    """Read-only avatar configuration owned by the Scholens API runtime."""

    model_config = SettingsConfigDict(
        env_prefix="SHARED_AVATAR_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    bucket: str = ""
    url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    max_concurrency: int = Field(default=8, ge=1, le=32)
    cache_max_entries: int = Field(default=2048, ge=1, le=10_000)
    cache_refresh_skew_seconds: int = Field(default=60, ge=5, le=300)
    missing_cache_ttl_seconds: int = Field(default=60, ge=5, le=900)

    @property
    def configured(self) -> bool:
        return bool(self.bucket.strip())


class SanchezCloudSharedAvatarReader(SharedAvatarReader):
    """Bounded, read-only facade over the shared identity avatar manager."""

    def __init__(
        self,
        manager: AvatarManager | None,
        *,
        max_concurrency: int,
        cache_max_entries: int = 2048,
        cache_refresh_skew_seconds: int = 60,
        missing_cache_ttl_seconds: int = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._manager = manager
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache_max_entries = cache_max_entries
        self._cache_refresh_skew = timedelta(seconds=cache_refresh_skew_seconds)
        self._missing_cache_ttl = timedelta(seconds=missing_cache_ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[int, _AvatarCacheEntry] = OrderedDict()
        self._inflight: dict[int, asyncio.Task[AvatarReference]] = {}

    async def get(self, user_id: int) -> AvatarReference:
        if self._manager is None:
            raise SharedAvatarUnavailableError("Shared avatars are not configured")
        cached: AvatarReference | None | object = _CACHE_MISS
        async with self._lock:
            entry = self._cache.get(user_id)
            if entry is not None:
                if self._clock() < entry.valid_until:
                    self._cache.move_to_end(user_id)
                    cached = entry.avatar
                else:
                    self._cache.pop(user_id, None)
            task = self._inflight.get(user_id)
            if cached is _CACHE_MISS and task is None:
                task = asyncio.create_task(self._load_and_cache(user_id))
                self._inflight[user_id] = task

        if cached is None:
            raise SharedAvatarNotFoundError("Shared avatar not found")
        if cached is not _CACHE_MISS:
            return cast(AvatarReference, cached)
        assert task is not None
        return await asyncio.shield(task)

    async def _load_and_cache(self, user_id: int) -> AvatarReference:
        try:
            async with self._semaphore:
                assert self._manager is not None
                view = await self._manager.get(user_id)
        except AvatarNotFoundError as exc:
            await self._store(
                user_id,
                avatar=None,
                valid_until=self._clock() + self._missing_cache_ttl,
            )
            raise SharedAvatarNotFoundError("Shared avatar not found") from exc
        except Exception as exc:
            add_counter("scholens.shared_avatar.read_failed")
            logger.warning(
                "shared_avatar_read_failed",
                extra={
                    "exception_type": type(exc).__name__,
                    "failure_stage": _failure_stage(exc),
                },
                exc_info=True,
            )
            raise SharedAvatarUnavailableError(
                "Shared avatar service unavailable"
            ) from exc
        else:
            avatar = AvatarReference(
                url=view.url,
                version=view.version,
                expires_at=view.expires_at,
            )
            valid_until = avatar.expires_at - self._cache_refresh_skew
            if self._clock() < valid_until:
                await self._store(
                    user_id,
                    avatar=avatar,
                    valid_until=valid_until,
                )
            return avatar
        finally:
            current_task = asyncio.current_task()
            async with self._lock:
                if self._inflight.get(user_id) is current_task:
                    self._inflight.pop(user_id, None)

    async def _store(
        self,
        user_id: int,
        *,
        avatar: AvatarReference | None,
        valid_until: datetime,
    ) -> None:
        async with self._lock:
            self._cache[user_id] = _AvatarCacheEntry(
                avatar=avatar,
                valid_until=valid_until,
            )
            self._cache.move_to_end(user_id)
            while len(self._cache) > self._cache_max_entries:
                self._cache.popitem(last=False)

    async def get_many(self, user_ids: set[int]) -> dict[int, AvatarReference]:
        async def resolve(user_id: int) -> tuple[int, AvatarReference | None]:
            try:
                return user_id, await self.get(user_id)
            except SharedAvatarNotFoundError:
                return user_id, None

        if not user_ids:
            return {}
        resolved = await asyncio.gather(*(resolve(user_id) for user_id in user_ids))
        return {user_id: avatar for user_id, avatar in resolved if avatar is not None}


def _build_reader(settings: SharedAvatarSettings) -> SanchezCloudSharedAvatarReader:
    manager: AvatarManager | None = None
    if settings.configured:
        client = boto3.client(
            "s3",
            config=Config(signature_version="s3v4"),
        )
        manager = AvatarManager(
            database=AsyncpgAvatarDatabase(pool_factory=get_auth_pool),
            storage=S3AvatarStorage(
                client=cast(Any, client),
                bucket=settings.bucket,
            ),
            url_ttl_seconds=settings.url_ttl_seconds,
        )
    return SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=settings.max_concurrency,
        cache_max_entries=settings.cache_max_entries,
        cache_refresh_skew_seconds=settings.cache_refresh_skew_seconds,
        missing_cache_ttl_seconds=settings.missing_cache_ttl_seconds,
    )


@lru_cache(maxsize=1)
def get_shared_avatar_reader() -> SharedAvatarReader:
    return _build_reader(SharedAvatarSettings())


__all__ = [
    "SanchezCloudSharedAvatarReader",
    "SharedAvatarSettings",
    "get_shared_avatar_reader",
]
