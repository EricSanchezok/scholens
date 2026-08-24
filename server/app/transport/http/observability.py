"""Canonical HTTP request identity, logging and metric boundary."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import nullcontext
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from app.shared.application import OperationContext
from app.transport.client_ip import apply_trusted_proxy_scheme, resolve_scope_client_ip
from scholens_observability import (
    ObservabilityContext,
    build_snapshot,
    add_counter,
    bind_context,
    log_event,
    record_histogram,
    should_sample_success,
    update_context,
)
from fastapi import Request
from opentelemetry.instrumentation.utils import suppress_instrumentation
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_READING_ACTIVITY_PATH_TEMPLATES = (
    (
        re.compile(r"^/api/v1/me/reading-activity-preferences/?$"),
        "/api/v1/me/reading-activity-preferences",
    ),
    (
        re.compile(r"^/api/v1/papers/[^/]+/reading-sessions/?$"),
        "/api/v1/papers/{document_id}/reading-sessions",
    ),
    (
        re.compile(r"^/api/v1/reading-sessions/[^/]+/?$"),
        "/api/v1/reading-sessions/{session_id}",
    ),
    (
        re.compile(r"^(/api/v1/papers)/[^/]+(/(?:insights|reading-activity))/?$"),
        r"\1/{document_id}\2",
    ),
    (
        re.compile(
            r"^(/api/v1/projects)/[^/]+/"
            r"(insights|activity|me/reading-activity)/?$"
        ),
        r"\1/{project_id}/\2",
    ),
    (
        re.compile(r"^/api/v1/me/research-insights/?$"),
        "/api/v1/me/research-insights",
    ),
    (
        re.compile(r"^/api/v1/me/reading-activity(?:/paper-summaries|/export)?/?$"),
        "",
    ),
)
_UUID_PATH_SEGMENT = re.compile(
    r"(?<=/)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)


def ensure_request_id(request: Request) -> UUID:
    """Return the middleware request ID, recovering safely at direct boundaries."""

    raw_request_id = getattr(request.state, "request_id", None)
    try:
        request_id = UUID(str(raw_request_id))
    except (TypeError, ValueError, AttributeError):
        request_id = uuid4()
        request.state.request_id = str(request_id)
    return request_id


def attach_operation_context(
    request: Request,
    operation: OperationContext,
    *,
    actor_id: str | None = None,
) -> None:
    """Project authenticated business provenance into diagnostic context."""

    request.state.operation_context = operation
    request.state.operation_id = str(operation.trace.operation_id)
    request.state.correlation_id = str(operation.trace.correlation_id)
    if actor_id is not None:
        request.state.actor_id = actor_id
    update_context(
        actor_id=actor_id,
        operation_id=str(operation.trace.operation_id),
        correlation_id=str(operation.trace.correlation_id),
        causation_id=(
            str(operation.trace.causation_id)
            if operation.trace.causation_id is not None
            else None
        ),
        origin=operation.origin.kind,
    )


def is_reading_activity_request(scope: Scope) -> bool:
    """Identify the privacy-sensitive activity surface before routing."""

    path = str(scope.get("path", ""))
    return _reading_activity_route_template(path) is not None


def _reading_activity_route_template(path: str) -> str | None:
    for pattern, replacement in _READING_ACTIVITY_PATH_TEMPLATES:
        if pattern.fullmatch(path) is None:
            continue
        if replacement:
            return pattern.sub(replacement, path)
        return path.removesuffix("/")
    return None


class RequestObservabilityMiddleware:
    """Keep diagnostic context alive until a streamed response fully closes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        service: str,
        environment: str,
        release: str | None,
        success_sample_rate: float = 0.01,
    ) -> None:
        self._app = app
        self._base_context = ObservabilityContext(
            service=service,
            environment=environment,
            release=release,
        )
        self._success_sample_rate = success_sample_rate
        self._environment = environment

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = str(uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        application = scope.get("app")
        runtime_settings = getattr(
            getattr(application, "state", None), "settings", None
        )
        state["client_ip"] = resolve_scope_client_ip(
            scope,
            environment=self._environment,
            trust_cloudflare=bool(
                getattr(runtime_settings, "trust_cloudflare_client_ip", False)
            ),
            trusted_proxy_cidr=getattr(runtime_settings, "trusted_proxy_cidr", None),
        )
        apply_trusted_proxy_scheme(
            scope,
            environment=self._environment,
            trust_cloudflare=bool(
                getattr(runtime_settings, "trust_cloudflare_client_ip", False)
            ),
            trusted_proxy_cidr=getattr(runtime_settings, "trusted_proxy_cidr", None),
        )
        started = monotonic()
        response_status = 500
        response_started = False
        private_reading = is_reading_activity_request(scope)

        async def observed_send(message: Message) -> None:
            nonlocal response_status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_status = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                correlation_id = state.get("correlation_id")
                if isinstance(correlation_id, str):
                    headers.append(
                        (b"x-correlation-id", correlation_id.encode("ascii"))
                    )
                message["headers"] = headers
            await send(message)

        with bind_context(**self._base_context.fields(), request_id=request_id):
            if not private_reading:
                log_event(
                    logger,
                    logging.INFO,
                    "http.request.started",
                    method=scope.get("method", "UNKNOWN"),
                    client_ip=state["client_ip"],
                )
            try:
                instrumentation_scope = (
                    suppress_instrumentation() if private_reading else nullcontext()
                )
                with instrumentation_scope:
                    await self._app(scope, receive, observed_send)
            except asyncio.CancelledError:
                duration_ms = (monotonic() - started) * 1000
                add_counter("scholens.http.client_disconnected")
                if not private_reading:
                    log_event(
                        logger,
                        logging.INFO,
                        "http.request.client_disconnected",
                        method=scope.get("method", "UNKNOWN"),
                        route=safe_http_route_template(scope),
                        duration_ms=round(duration_ms, 3),
                        client_ip=state["client_ip"],
                    )
                raise
            finally:
                duration_ms = (monotonic() - started) * 1000
                route = safe_http_route_template(scope)
                attributes: dict[str, str | int | float | bool] = {
                    "method": str(scope.get("method", "UNKNOWN")),
                    "route": route,
                    "status_code": response_status,
                }
                add_counter("scholens.http.requests", attributes=attributes)
                record_histogram(
                    "scholens.http.duration",
                    duration_ms,
                    attributes=attributes,
                )
                if response_status >= 500:
                    add_counter("scholens.http.server_errors", attributes=attributes)
                stream_failed = bool(state.get("stream_failed"))
                if stream_failed:
                    add_counter("scholens.http.stream_failures")
                if not private_reading:
                    log_event(
                        logger,
                        logging.INFO if response_status < 500 else logging.ERROR,
                        "http.request.completed",
                        method=scope.get("method", "UNKNOWN"),
                        route=route,
                        status_code=response_status,
                        response_started=response_started,
                        stream_failed=stream_failed,
                        duration_ms=round(duration_ms, 3),
                        client_ip=state["client_ip"],
                    )
                    self._record_sampled_success(
                        scope=scope,
                        state=state,
                        route=route,
                        status_code=response_status,
                        duration_ms=duration_ms,
                    )

    def _record_sampled_success(
        self,
        *,
        scope: Scope,
        state: dict[str, Any],
        route: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        correlation_id = state.get("correlation_id")
        if (
            status_code >= 400
            or str(scope.get("method", "GET")).upper() in {"GET", "HEAD", "OPTIONS"}
            or not state.get("authenticated")
            or not isinstance(correlation_id, str)
            or not should_sample_success(
                correlation_id,
                rate=self._success_sample_rate,
            )
        ):
            return
        application = scope.get("app")
        app_state = getattr(application, "state", None)
        recorder = getattr(app_state, "diagnostic_snapshot_recorder", None)
        if recorder is None:
            return
        snapshot = build_snapshot(
            snapshot_id=uuid4(),
            service=self._base_context.service,
            environment=self._base_context.environment,
            release=self._base_context.release,
            reason="http_success_sample",
            request_id=state.get("request_id"),
            operation_id=state.get("operation_id"),
            correlation_id=correlation_id,
            actor_id=state.get("actor_id"),
            sections={
                "request": {
                    "method": str(scope.get("method", "UNKNOWN")),
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                }
            },
        )
        recorder.record(snapshot)


def safe_http_route_template(scope: Scope) -> str:
    """Return a bounded route label without resource identifiers or query data."""

    route: Any = scope.get("route")
    path = getattr(route, "path", None)
    raw = str(path) if path else str(scope.get("path", "unknown"))
    reading_route = _reading_activity_route_template(raw)
    if reading_route is not None:
        return reading_route
    return _UUID_PATH_SEGMENT.sub("{id}", raw)
