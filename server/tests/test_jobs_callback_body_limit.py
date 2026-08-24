from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from app.bootstrap.execution import get_job_completion_processor
from app.shared.domain import AppError, FailureKind
from app.transport.http.internal_v1 import authentication
from app.transport.http.internal_v1.jobs_callbacks.lifecycle import (
    lifecycle_webhook_router,
)
from app.transport.http.internal_v1.jobs_callbacks.router import webhook_router
from app.transport.http.internal_v1.jobs_callbacks.terminal import terminal_router
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.requests import Request


def _request(
    *,
    body: bytes,
    content_length: str | None = None,
    extra_chunks: tuple[bytes, ...] = (),
) -> tuple[Request, dict[str, int]]:
    chunks = iter((body, *extra_chunks))
    state = {"received": 0}

    async def receive() -> dict[str, object]:
        try:
            chunk = next(chunks)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        state["received"] += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": state["received"] <= len(extra_chunks),
        }

    headers = (
        []
        if content_length is None
        else [(b"content-length", content_length.encode("ascii"))]
    )
    return (
        Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/internal/v1/jobs/example/complete",
                "query_string": b"",
                "headers": headers,
            },
            receive,
        ),
        state,
    )


def test_declared_oversized_callback_is_rejected_before_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication, "MAX_JOBS_CALLBACK_BODY_BYTES", 8)
    request, state = _request(body=b"not-read", content_length="9")

    with pytest.raises(AppError) as rejected:
        authentication._require_bounded_callback_size(
            authentication._declared_body_size(request) or 0
        )

    assert rejected.value.code == "jobs_callback_too_large"
    assert rejected.value.kind is FailureKind.PAYLOAD_TOO_LARGE
    assert state["received"] == 0


@pytest.mark.asyncio
async def test_chunked_oversized_callback_stops_before_later_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication, "MAX_JOBS_CALLBACK_BODY_BYTES", 8)
    request, state = _request(
        body=b"1234",
        extra_chunks=(b"5678", b"9", b"must-not-be-read"),
    )

    with pytest.raises(AppError) as rejected:
        await authentication._read_bounded_callback_body(request)

    assert rejected.value.code == "jobs_callback_too_large"
    assert state["received"] == 3


@pytest.mark.asyncio
async def test_bounded_stream_is_cached_for_fastapi_payload_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication, "MAX_JOBS_CALLBACK_BODY_BYTES", 8)
    request, state = _request(body=b"1234", extra_chunks=(b"56",))

    assert await authentication._read_bounded_callback_body(request) == b"123456"
    assert await request.body() == b"123456"
    assert state["received"] == 2


def test_invalid_content_length_is_rejected() -> None:
    with pytest.raises(AppError) as rejected:
        authentication._declared_body_size(
            _request(body=b"", content_length="not-a-number")[0]
        )

    assert rejected.value.code == "jobs_callback_size_invalid"
    assert rejected.value.kind is FailureKind.INVALID_ARGUMENT


def test_callback_routes_do_not_declare_eager_fastapi_body_fields() -> None:
    body_routes = {
        route.path: route.body_field
        for route in (*terminal_router.routes, *lifecycle_webhook_router.routes)
        if isinstance(route, APIRoute)
        and route.path.endswith(("/complete", "/fail", "/progress"))
    }

    assert body_routes == {
        "/jobs/{job_id}/complete": None,
        "/jobs/{job_id}/fail": None,
        "/jobs/{job_id}/progress": None,
    }


@pytest.mark.asyncio
async def test_actual_callback_route_stops_chunked_body_before_later_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication, "MAX_JOBS_CALLBACK_BODY_BYTES", 8)
    monkeypatch.setenv("JOBS_WEBHOOK_SIGNING_SECRET", "s" * 32)

    app = FastAPI()

    async def handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AppError)
        return JSONResponse(status_code=413, content={"code": exc.code})

    app.add_exception_handler(AppError, handle_app_error)
    app.dependency_overrides[get_job_completion_processor] = lambda: object()
    app.include_router(webhook_router, prefix="/internal/v1")

    chunks = iter((b"1234", b"5678", b"9", b"must-not-be-read"))
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        chunk = next(chunks)
        received += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": received < 4,
        }

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    job_id = uuid.uuid4()
    path = f"/internal/v1/jobs/{job_id}/complete"
    headers = [
        (b"host", b"testserver"),
        (b"content-type", b"application/json"),
        (b"x-jobs-timestamp", str(int(time.time())).encode("ascii")),
        (b"x-jobs-nonce", b"bounded-route-test"),
        (b"x-jobs-signature", b"not-reached"),
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
        "state": {},
    }

    application: Callable[
        [
            dict[str, Any],
            Callable[[], Awaitable[dict[str, Any]]],
            Callable[..., Awaitable[None]],
        ],
        Awaitable[None],
    ] = app
    await application(scope, receive, send)

    assert received == 3
    assert (
        next(message for message in sent if message["type"] == "http.response.start")[
            "status"
        ]
        == 413
    )
    response_body = next(
        message["body"] for message in sent if message["type"] == "http.response.body"
    )
    assert response_body == b'{"code":"jobs_callback_too_large"}'
