"""Credential-scoped access to the official OpenAlex REST API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, NoReturn, cast
from urllib.parse import quote

import httpx
from app.modules.papers.application.contracts.discovery import (
    EnrichedData,
    OpenAlexCitationGraph,
    OpenAlexResponse,
    OpenAlexWork,
)
from app.modules.papers.domain import normalize_doi
from app.shared.domain import AppError, FailureKind
from pydantic import ValidationError

logger = logging.getLogger(__name__)

OPENALEX_API_BASE_URL = "https://api.openalex.org"
_MAX_ATTEMPTS = 3
_REQUEST_TIMEOUT_SECONDS = 10.0
_RETRY_DELAY_SECONDS = 0.25


class _UnsafeOpenAlexRedirect(httpx.TransportError):
    """A deterministic origin-policy failure that must not be retried."""


class OpenAlexApiClient:
    """Small typed client whose API key never escapes the request boundary."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay_seconds: float = _RETRY_DELAY_SECONDS,
    ) -> None:
        self._retry_delay_seconds = retry_delay_seconds
        self._client = httpx.AsyncClient(
            base_url=OPENALEX_API_BASE_URL,
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            transport=_CredentialTransport(transport=transport),
        )

    async def probe(self, *, api_key: str) -> None:
        await self._get("/rate-limit", api_key=api_key)

    async def search(
        self,
        *,
        api_key: str,
        query: str,
        page: int,
    ) -> OpenAlexResponse:
        payload = await self._get(
            "/works",
            api_key=api_key,
            params={"search": query, "page": page},
        )
        return self._response(payload)

    async def author_works(
        self,
        *,
        api_key: str,
        author_id: str,
        page: int,
    ) -> OpenAlexResponse:
        payload = await self._get(
            "/works",
            api_key=api_key,
            params={"filter": f"authorships.author.id:{author_id}", "page": page},
        )
        return self._response(payload)

    async def resolve_doi(
        self,
        *,
        api_key: str,
        title: str,
        authors: list[str] | None = None,
    ) -> str | None:
        results = await self.search(api_key=api_key, query=title, page=1)
        target_authors = {author.casefold() for author in authors or []}
        for work in results.results:
            if title.casefold() not in work.title.casefold():
                continue
            if target_authors:
                work_authors = {
                    authorship.author.display_name.casefold()
                    for authorship in work.authorships or []
                    if authorship.author and authorship.author.display_name
                }
                if not work_authors.intersection(target_authors):
                    continue
            return _doi_from_value(work.doi)
        return None

    async def find_by_doi(
        self,
        *,
        api_key: str,
        doi: str,
    ) -> OpenAlexWork | None:
        identifier = quote(f"doi:{doi}", safe=":")
        payload = await self._get(
            f"/works/{identifier}",
            api_key=api_key,
            not_found_ok=True,
        )
        return self._work(payload)

    async def citation_graph(
        self,
        *,
        api_key: str,
        work_id: str,
    ) -> OpenAlexCitationGraph:
        normalized_id = work_id.rstrip("/").rsplit("/", maxsplit=1)[-1]
        center_payload = await self._get(
            f"/works/{quote(normalized_id, safe='')}",
            api_key=api_key,
            not_found_ok=True,
        )
        center = self._work(center_payload)
        if center is None:
            raise AppError(
                code="openalex_paper_not_found",
                message="OpenAlex could not find this paper",
                kind=FailureKind.NOT_FOUND,
            )
        cited_by_payload, cites_payload = await asyncio.gather(
            self._get(
                "/works",
                api_key=api_key,
                params={
                    "filter": f"cites:{normalized_id}",
                    "page": 1,
                    "per_page": 20,
                },
            ),
            self._get(
                "/works",
                api_key=api_key,
                params={
                    "filter": f"cited_by:{normalized_id}",
                    "page": 1,
                    "per_page": 20,
                },
            ),
        )
        return OpenAlexCitationGraph(
            center=center,
            cites=self._response(cites_payload),
            cited_by=self._response(cited_by_payload),
        )

    async def enriched_data(
        self,
        *,
        api_key: str,
        doi: str,
    ) -> EnrichedData | None:
        work = await self.find_by_doi(api_key=api_key, doi=doi)
        if work is None:
            return None
        source = work.primary_location.source if work.primary_location else None
        publisher = None
        if source and source.host_organization:
            publisher = await self._organization_name(
                api_key=api_key,
                identifier=source.host_organization,
            )
        return EnrichedData(
            publisher=publisher,
            journal=source.display_name if source else None,
            publication_date=work.publication_date,
            title=work.title,
        )

    async def _organization_name(
        self,
        *,
        api_key: str,
        identifier: str,
    ) -> str | None:
        organization_id = identifier.rstrip("/").rsplit("/", maxsplit=1)[-1]
        if organization_id.startswith("P"):
            entity = "publishers"
        elif organization_id.startswith("I"):
            entity = "institutions"
        else:
            return None
        payload = await self._get(
            f"/{entity}/{quote(organization_id, safe='')}",
            api_key=api_key,
            not_found_ok=True,
        )
        if not isinstance(payload, Mapping):
            return None
        display_name = payload.get("display_name")
        return display_name if isinstance(display_name, str) else None

    async def _get(
        self,
        path: str,
        *,
        api_key: str,
        params: Mapping[str, str | int] | None = None,
        not_found_ok: bool = False,
    ) -> object | None:
        request_params = dict(params or {})
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await self._client.get(
                    path,
                    params=request_params,
                    extensions={"openalex_api_key": api_key},
                )
            except _UnsafeOpenAlexRedirect:
                self._unavailable("unsafe_redirect")
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt < _MAX_ATTEMPTS - 1:
                    await self._backoff(attempt)
                    continue
                self._unavailable("transport")

            if response.status_code == 404 and not_found_ok:
                return None
            if response.status_code == 200:
                try:
                    return cast(object, response.json())
                except ValueError:
                    self._unavailable("invalid_json")

            message = _safe_provider_message(response)
            logger.warning(
                "openalex.request.failed",
                extra={
                    "http_status": response.status_code,
                    "provider_request_id": response.headers.get("x-request-id")
                    or response.headers.get("request-id"),
                    "retry_after": response.headers.get("retry-after"),
                    "error_class": (
                        "credential"
                        if _is_invalid_credential(response.status_code, message)
                        else "rate_limit"
                        if response.status_code == 429
                        else "server"
                        if response.status_code >= 500
                        else "client"
                    ),
                },
            )
            if _is_invalid_credential(response.status_code, message):
                raise AppError(
                    code="openalex_credential_invalid",
                    message="The connected OpenAlex API key is invalid",
                    kind=FailureKind.UNPROCESSABLE,
                    retryable=True,
                    details={"required_integration": "openalex"},
                )
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                raise AppError(
                    code="openalex_rate_limited",
                    message="OpenAlex is rate limiting this account",
                    kind=FailureKind.RATE_LIMITED,
                    retryable=True,
                    details={"retry_after_seconds": retry_after},
                )
            if response.status_code >= 500 and attempt < _MAX_ATTEMPTS - 1:
                await self._backoff(attempt, retry_after=_retry_after_seconds(response))
                continue
            self._unavailable(f"http_{response.status_code}")
        self._unavailable("no_response")

    async def _backoff(self, attempt: int, *, retry_after: float = 0.0) -> None:
        await asyncio.sleep(max(retry_after, self._retry_delay_seconds * (2**attempt)))

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _work(payload: object | None) -> OpenAlexWork | None:
        if payload is None:
            return None
        try:
            return OpenAlexWork.model_validate(payload)
        except ValidationError:
            OpenAlexApiClient._unavailable("invalid_work")

    @staticmethod
    def _response(payload: object | None) -> OpenAlexResponse:
        try:
            return OpenAlexResponse.model_validate(payload)
        except ValidationError:
            OpenAlexApiClient._unavailable("invalid_response")

    @staticmethod
    def _unavailable(reason: str) -> NoReturn:
        logger.warning("openalex.request.unavailable", extra={"reason": reason})
        raise AppError(
            code="openalex_unavailable",
            message="OpenAlex is temporarily unavailable",
            kind=FailureKind.DEPENDENCY_FAILURE,
            retryable=True,
        )


def _safe_provider_message(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, Mapping):
        return ""
    return " ".join(
        str(payload.get(key, "")) for key in ("error", "message")
    ).casefold()


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("retry-after")
    if value is None:
        return 0.0
    try:
        return max(0.0, min(float(value), 30.0))
    except ValueError:
        return 0.0


class _CredentialTransport(httpx.AsyncBaseTransport):
    """Add the query credential below HTTPX's URL logging boundary."""

    __slots__ = ("_transport",)

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self._transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != "api.openalex.org"
            or request.url.port not in {None, 443}
        ):
            raise _UnsafeOpenAlexRedirect(
                "OpenAlex redirected to a disallowed origin",
                request=request,
            )
        api_key = request.extensions.get("openalex_api_key")
        if not isinstance(api_key, str) or not api_key:
            raise _UnsafeOpenAlexRedirect(
                "OpenAlex request credential is missing",
                request=request,
            )
        provider_request = httpx.Request(
            method=request.method,
            url=request.url.copy_add_param("api_key", api_key),
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return await self._transport.handle_async_request(provider_request)

    async def aclose(self) -> None:
        await self._transport.aclose()


def _is_invalid_credential(status_code: int, message: str) -> bool:
    if status_code == 401:
        return True
    return "api key" in message and any(
        marker in message for marker in ("invalid", "missing", "unknown")
    )


def _doi_from_value(value: str | None) -> str | None:
    return normalize_doi(value)


__all__ = ["OPENALEX_API_BASE_URL", "OpenAlexApiClient"]
