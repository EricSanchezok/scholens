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
        (403, {"error": "forbidden"}, "openalex_unavailable"),
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


@pytest.mark.asyncio
async def test_openalex_client_does_not_forward_key_across_origins() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            301,
            headers={"location": "https://attacker.example/collect"},
        )

    client = OpenAlexApiClient(
        transport=httpx.MockTransport(handler),
        retry_delay_seconds=0,
    )

    with pytest.raises(AppError) as raised:
        await client.find_by_doi(api_key=API_KEY, doi="10.1000/example")

    assert raised.value.code == "openalex_unavailable"
    assert len(observed) == 1
    assert observed[0].url.host == "api.openalex.org"


@pytest.mark.asyncio
async def test_openalex_citation_graph_preserves_edge_direction() -> None:
    def list_payload(title: str) -> dict[str, object]:
        return {
            "meta": {"count": 1, "per_page": 20},
            "results": [{"id": f"https://openalex.org/{title}", "title": title}],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        citation_filter = request.url.params.get("filter")
        if citation_filter == "cites:W1":
            return httpx.Response(200, json=list_payload("incoming-citation"))
        if citation_filter == "cited_by:W1":
            return httpx.Response(200, json=list_payload("outgoing-citation"))
        return httpx.Response(
            200,
            json={"id": "https://openalex.org/W1", "title": "Center"},
        )

    client = OpenAlexApiClient(
        transport=httpx.MockTransport(handler),
        retry_delay_seconds=0,
    )

    graph = await client.citation_graph(api_key=API_KEY, work_id="W1")

    assert [work.title for work in graph.cites.results] == ["outgoing-citation"]
    assert [work.title for work in graph.cited_by.results] == ["incoming-citation"]


@pytest.mark.asyncio
async def test_openalex_missing_center_does_not_spend_list_credits() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(404, json={"error": "not found"})

    client = OpenAlexApiClient(
        transport=httpx.MockTransport(handler),
        retry_delay_seconds=0,
    )

    with pytest.raises(AppError) as raised:
        await client.citation_graph(api_key=API_KEY, work_id="W404")

    assert raised.value.code == "openalex_paper_not_found"
    assert len(observed) == 1
