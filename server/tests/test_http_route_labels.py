"""Real router composition must retain the labels used by business alarms."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.observability.runtime import _fastapi_request_hook
from app.transport.http import observability


@pytest.mark.parametrize("root_path", ["", "/edge"])
@pytest.mark.parametrize("prefix", ["/internal/v1", "/alternate/v1"])
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_included_receipt_routes_keep_full_parameterized_labels(
    monkeypatch: pytest.MonkeyPatch,
    root_path: str,
    prefix: str,
    method: str,
) -> None:
    app = FastAPI(root_path=root_path)
    child, parent = APIRouter(), APIRouter()
    completed: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []

    def log(_logger: object, _level: int, event: str, **fields: object) -> None:
        if event == "http.request.completed":
            completed.append(fields)

    def metric(_name: str, **fields: object) -> None:
        metrics.append(fields)

    monkeypatch.setattr(observability, "log_event", log)
    monkeypatch.setattr(observability, "add_counter", metric)

    @child.post("/jobs/{job_id}/results")
    def receipt(job_id: UUID, request: Request) -> dict[str, str]:
        span = MagicMock()
        _fastapi_request_hook(span, request.scope)
        labels = dict(call.args for call in span.set_attribute.call_args_list)
        return {"route": labels["http.route"]}

    parent.include_router(child)
    app.include_router(parent, prefix="/internal/v1")
    app.include_router(parent, prefix="/alternate/v1")
    app.add_middleware(
        observability.RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release=None,
    )
    expected = prefix + "/jobs/{job_id}/results"
    with TestClient(app) as client:
        # The same route object is included twice. Reusing the catalog must not
        # remember the first request's prefix as the next request's label.
        first = client.post(
            root_path + "/internal/v1/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/results"
        )
        assert first.json() == {"route": "/internal/v1/jobs/{job_id}/results"}
        response = client.request(
            method,
            root_path + prefix + "/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/results",
        )
    assert response.status_code == (200 if method == "POST" else 405)
    if method == "POST":
        assert response.json() == {"route": expected}
    assert completed[-1]["route"] == expected
    assert any(
        fields.get("attributes", {}).get("route") == expected for fields in metrics
    )


def test_included_route_error_keeps_its_template() -> None:
    app, child = FastAPI(), APIRouter()

    @child.get("/papers/{document_id}")
    def fail(document_id: UUID, request: Request) -> None:
        raise HTTPException(
            409, detail=observability.safe_http_route_template(request.scope)
        )

    app.include_router(child, prefix="/api/v1/library")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/library/papers/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "/api/v1/library/papers/{document_id}"
