"""User-owned OpenAlex access with short credential and outcome transactions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from uuid import UUID

from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.papers.application.contracts.discovery import (
    EnrichedData,
    OpenAlexCitationGraph,
    OpenAlexResponse,
    OpenAlexWork,
)
from app.modules.papers.infrastructure.openalex import OpenAlexApiClient
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError
from app.bootstrap.cache_endpoint import cache_url_from_environment
from redis.asyncio import Redis
from redis.exceptions import RedisError

T = TypeVar("T")
OpenAlexCall = Callable[[OpenAlexApiClient, str], Awaitable[T]]
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.bootstrap.capabilities import ApplicationCapabilities


class UserOpenAlex:
    """Resolve one actor's current credential for one provider request."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operation_factory: OperationContextFactory,
        client: OpenAlexApiClient | None = None,
    ) -> None:
        self._executor = executor
        self._operation_factory = operation_factory
        self._client = client or OpenAlexApiClient()
        self._doi_cache: dict[str, tuple[float, OpenAlexWork | None]] = {}
        cache_url = cache_url_from_environment()
        self._redis_cache = (
            Redis.from_url(
                cache_url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
            )
            if cache_url
            else None
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        if self._redis_cache is not None:
            await self._redis_cache.aclose()

    async def probe(self, *, api_key: str) -> None:
        await self._client.probe(api_key=api_key)

    async def search(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        query: str,
        page: int,
    ) -> OpenAlexResponse:
        return await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.search(
                api_key=api_key,
                query=query,
                page=page,
            ),
        )

    async def author_works(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        author_id: str,
        page: int,
    ) -> OpenAlexResponse:
        return await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.author_works(
                api_key=api_key,
                author_id=author_id,
                page=page,
            ),
        )

    async def resolve_doi(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        title: str,
        authors: list[str] | None = None,
    ) -> str | None:
        return await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.resolve_doi(
                api_key=api_key,
                title=title,
                authors=authors,
            ),
        )

    async def find_by_doi(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        doi: str,
    ) -> OpenAlexWork | None:
        cache_key = doi.casefold()
        cached = self._doi_cache.get(cache_key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        redis_key = (
            "scholens:openalex:doi:" + hashlib.sha256(cache_key.encode()).hexdigest()
        )
        if self._redis_cache is not None:
            try:
                cached_payload = await self._redis_cache.get(redis_key)
                if cached_payload:
                    cached_result = OpenAlexWork.model_validate(
                        json.loads(cached_payload)
                    )
                    self._doi_cache[cache_key] = (
                        time.monotonic() + 12 * 3600,
                        cached_result,
                    )
                    return cached_result
            except (RedisError, TypeError, ValueError):
                logger.warning("openalex.cache.read_failed", exc_info=True)
        result = await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.find_by_doi(
                api_key=api_key,
                doi=doi,
            ),
        )
        # Metadata is public and credential-free. Keep this bounded process
        # cache to collapse repeated DOI lookups in one batch without adding a
        # paid cache dependency or persisting credentials.
        self._doi_cache[cache_key] = (
            time.monotonic() + (12 * 3600 if result is not None else 600),
            result,
        )
        if self._redis_cache is not None and result is not None:
            try:
                await self._redis_cache.set(
                    redis_key,
                    json.dumps(result.model_dump(mode="json"), separators=(",", ":")),
                    ex=12 * 3600,
                )
            except RedisError:
                logger.warning("openalex.cache.write_failed", exc_info=True)
        if len(self._doi_cache) > 2048:
            oldest = min(self._doi_cache, key=lambda key: self._doi_cache[key][0])
            self._doi_cache.pop(oldest, None)
        return result

    async def citation_graph(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        work_id: str,
    ) -> OpenAlexCitationGraph:
        return await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.citation_graph(
                api_key=api_key,
                work_id=work_id,
            ),
        )

    def resolve_doi_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        title: str,
        authors: list[str] | None = None,
    ) -> str | None:
        return _run_sync(
            lambda: self.resolve_doi(
                actor=actor,
                operation=operation,
                title=title,
                authors=authors,
            )
        )

    def enriched_data_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        doi: str,
    ) -> EnrichedData | None:
        return self.request_sync(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.enriched_data(
                api_key=api_key,
                doi=doi,
            ),
        )

    async def request(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        call: OpenAlexCall[T],
    ) -> T:
        credential = self._executor.query(
            lambda capabilities: capabilities.integrations.credential(
                actor=actor,
                provider=IntegrationProvider.OPENALEX,
            )
        )
        try:
            result = await call(self._client, credential.secret)
        except AppError as exc:
            self._record_outcome(
                actor=actor,
                operation=operation,
                credential_revision=credential.revision,
                outcome=(
                    "invalid" if exc.code == "openalex_credential_invalid" else "failed"
                ),
                error_code=exc.code,
            )
            raise
        self._record_outcome(
            actor=actor,
            operation=operation,
            credential_revision=credential.revision,
            outcome="verified",
            error_code=None,
        )
        return result

    def request_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        call: OpenAlexCall[T],
    ) -> T:
        return _run_sync(
            lambda: self.request(actor=actor, operation=operation, call=call)
        )

    def _record_outcome(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        credential_revision: UUID,
        outcome: Literal["verified", "invalid", "failed"],
        error_code: str | None,
    ) -> None:
        provider_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        self._executor.command(
            lambda capabilities: capabilities.integrations.record_outcome(
                actor=actor,
                operation=provider_operation,
                provider=IntegrationProvider.OPENALEX,
                credential_revision=credential_revision,
                outcome=outcome,
                error_code=error_code,
            )
        )


def _run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="openalex") as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


__all__ = ["UserOpenAlex"]
