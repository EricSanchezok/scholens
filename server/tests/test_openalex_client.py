from __future__ import annotations

import logging

import httpx
import pytest

from app.modules.papers.infrastructure.openalex import OpenAlexApiClient
from app.shared.domain import AppError

API_KEY = "openalex-private-test-key"


@pytest.mark.asyncio
async def test_openalex_client_sends_key_only_as_query_parameter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json={"meta": {"count": 0, "per_page": 25}, "results": []},
        )

    client = OpenAlexApiClient(
        transport=httpx.MockTransport(handler),
        retry_delay_seconds=0,
    )

    with caplog.at_level(logging.INFO, logger="httpx"):
        result = await client.search(
            api_key=API_KEY,
            query="graph learning",
            page=2,
        )

    assert result.results == []
    assert len(observed) == 1
    request = observed[0]
    assert request.url.host == "api.openalex.org"
    assert request.url.path == "/works"
    assert request.url.params["api_key"] == API_KEY
    assert API_KEY not in request.url.path
    assert API_KEY not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload", "expected_code"),
    [
        (401, {"error": "unauthorized"}, "openalex_credential_invalid"),
        (400, {"error": "invalid api key"}, "openalex_credential_invalid"),
        (403, {"error": "quota exceeded"}, "openalex_rate_limited"),
        (429, {"error": "too many requests"}, "openalex_rate_limited"),
        (503, {"error": "maintenance"}, "openalex_unavailable"),
    ],
)
async def test_openalex_client_classifies_safe_provider_errors(
    status: int,
    payload: dict[str, str],
    expected_code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = OpenAlexApiClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, json=payload)
        ),
        retry_delay_seconds=0,
    )

    with caplog.at_level(logging.WARNING), pytest.raises(AppError) as raised:
        await client.probe(api_key=API_KEY)

    assert raised.value.code == expected_code
    assert API_KEY not in str(raised.value)
    assert API_KEY not in caplog.text


@pytest.mark.asyncio
async def test_openalex_work_404_preserves_not_found_semantics() -> None:
    client = OpenAlexApiClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(404, json={"error": "not found"})
        ),
        retry_delay_seconds=0,
    )

    assert await client.find_by_doi(api_key=API_KEY, doi="10.1000/example") is None
