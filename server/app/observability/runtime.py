"""Configure logging, tracing and safe automatic instrumentation."""

from __future__ import annotations

from threading import Lock
from typing import Any, Callable, cast
from urllib.parse import urlsplit, urlunsplit

from app.bootstrap.settings import AppSettings
from app.database.database import engine
from app.transport.http.observability import (
    is_reading_activity_request,
    safe_http_route_template,
)
from fastapi import FastAPI
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import (
    FastAPIInstrumentor,
)
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from scholens_observability import configure_logging, configure_telemetry

_LOCK = Lock()
_DEPENDENCIES_INSTRUMENTED = False


def _sanitized_url(value: object) -> str:
    """Keep route-level dependency telemetry without query strings or fragments."""

    parsed = urlsplit(str(value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _requests_request_hook(span: Any, request: Any) -> None:
    sanitized = _sanitized_url(getattr(request, "url", ""))
    span.set_attribute("url.full", sanitized)
    span.set_attribute("url.query", "")
    span.set_attribute("http.url", sanitized)


def _httpx_request_hook(span: Any, request: Any) -> None:
    sanitized = _sanitized_url(getattr(request, "url", ""))
    span.set_attribute("url.full", sanitized)
    span.set_attribute("url.query", "")
    span.set_attribute("http.url", sanitized)


async def _httpx_async_request_hook(span: Any, request: Any) -> None:
    _httpx_request_hook(span, request)


def _fastapi_request_hook(span: Any, scope: dict[str, Any]) -> None:
    route = getattr(scope.get("route"), "path", None)
    sanitized_path = str(route or safe_http_route_template(scope))
    scheme = str(scope.get("scheme", "http"))
    server = scope.get("server")
    authority = ""
    if isinstance(server, (list, tuple)) and server:
        authority = str(server[0])
        if len(server) > 1 and server[1] is not None:
            authority = f"{authority}:{int(server[1])}"
    sanitized_url = urlunsplit((scheme, authority, sanitized_path, "", ""))
    span.set_attribute("url.full", sanitized_url)
    span.set_attribute("http.url", sanitized_url)
    span.set_attribute("url.path", sanitized_path)
    span.set_attribute("http.target", sanitized_path)
    span.set_attribute("http.route", sanitized_path)
    span.set_attribute("url.query", "")
    method = str(scope.get("method", "HTTP")).upper()
    span.update_name(f"{method} {sanitized_path}")
    if is_reading_activity_request(scope):
        for attribute in (
            "client.address",
            "net.peer.ip",
            "http.client_ip",
            "user_agent.original",
            "enduser.id",
            "user.id",
        ):
            span.set_attribute(attribute, "")


def configure_application_observability(
    application: FastAPI,
    settings: AppSettings,
) -> None:
    configure_logging(
        service="scholens-api",
        environment=settings.environment,
        release=settings.release_sha,
    )
    configure_telemetry(
        service="scholens-api",
        environment=settings.environment,
        release=settings.release_sha,
        endpoint=settings.otel_exporter_otlp_endpoint,
    )
    if settings.otel_exporter_otlp_endpoint is None:
        return
    global _DEPENDENCIES_INSTRUMENTED
    with _LOCK:
        if not _DEPENDENCIES_INSTRUMENTED:
            RequestsInstrumentor().instrument(request_hook=_requests_request_hook)
            HTTPXClientInstrumentor().instrument(
                request_hook=_httpx_request_hook,
                async_request_hook=_httpx_async_request_hook,
            )
            SQLAlchemyInstrumentor().instrument(engine=engine)
            celery_instrumentor = cast(
                Callable[[], Any],
                CeleryInstrumentor,
            )()
            instrument_celery = cast(
                Callable[[], object],
                celery_instrumentor.instrument,
            )
            instrument_celery()
            redis_instrumentor = cast(
                Callable[[], Any],
                RedisInstrumentor,
            )()
            instrument_redis = cast(
                Callable[[], object],
                redis_instrumentor.instrument,
            )
            instrument_redis()
            _DEPENDENCIES_INSTRUMENTED = True
    FastAPIInstrumentor.instrument_app(
        application,
        server_request_hook=_fastapi_request_hook,
        excluded_urls="livez,readyz",
    )
