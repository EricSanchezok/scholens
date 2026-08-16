"""User-owned OpenAlex access with short credential and outcome transactions."""

from __future__ import annotations

import asyncio
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

T = TypeVar("T")
OpenAlexCall = Callable[[OpenAlexApiClient, str], Awaitable[T]]

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
        return await self.request(
            actor=actor,
            operation=operation,
            call=lambda client, api_key: client.find_by_doi(
                api_key=api_key,
                doi=doi,
            ),
        )

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
