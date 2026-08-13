"""Redis lease used only to collapse identical in-flight translations."""

from __future__ import annotations

import logging
import secrets

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

TRANSLATION_LEASE_TTL_SECONDS = 150
REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
REDIS_OPERATION_TIMEOUT_SECONDS = 1.0

_RELEASE_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisTranslationSingleFlight:
    def __init__(self, url: str | None) -> None:
        self._client = (
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=REDIS_OPERATION_TIMEOUT_SECONDS,
                retry_on_timeout=False,
            )
            if url is not None
            else None
        )

    async def acquire(self, key: str) -> str | None:
        token = secrets.token_urlsafe(24)
        if self._client is None:
            return token
        try:
            acquired = await self._client.set(
                self._lease_key(key),
                token,
                nx=True,
                ex=TRANSLATION_LEASE_TTL_SECONDS,
            )
            return token if acquired else None
        except RedisError:
            logger.exception("translation.singleflight.acquire_failed")
            return token

    async def release(self, key: str, lease_token: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.eval(
                _RELEASE_LEASE_SCRIPT,
                1,
                self._lease_key(key),
                lease_token,
            )
        except RedisError:
            logger.exception("translation.singleflight.release_failed")

    @staticmethod
    def _lease_key(key: str) -> str:
        return f"scholens:translation:lease:{key}"
