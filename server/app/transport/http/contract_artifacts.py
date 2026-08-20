"""Deterministic public OpenAPI and route-surface artifacts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

PUBLIC_PREFIX = "/api/v1"
SERVER_ROOT = Path(__file__).resolve().parents[3]
OUTPUT = SERVER_ROOT / "openapi" / "public-v1.json"
SURFACE_OUTPUT = SERVER_ROOT / "openapi" / "v1-contract.json"

_AUTH_FAILURES: dict[str, dict[str, tuple[int, ...]]] = {
    "/api/v1/auth/login": {"post": (401, 422, 429, 503)},
    "/api/v1/auth/register": {"post": (422, 429, 503)},
    "/api/v1/auth/verify-email": {"post": (400, 422, 503)},
    "/api/v1/auth/resend-verification": {"post": (422, 429, 503)},
    "/api/v1/auth/forgot-password": {"post": (422, 429, 503)},
    "/api/v1/auth/reset-password": {"post": (400, 422, 429, 503)},
    "/api/v1/auth/refresh": {"post": (401, 503)},
    "/api/v1/auth/bootstrap": {"post": (401, 503)},
    "/api/v1/auth/logout": {"post": (401, 503)},
    "/api/v1/auth/change-password": {"post": (400, 401, 422, 503)},
    "/api/v1/me": {"get": (401, 503)},
}
_STATUS_DESCRIPTIONS = {
    400: "Invalid or expired authentication token",
    401: "Authentication failed or session unavailable",
    422: "Request validation failed",
    429: "Authentication rate limit exceeded",
    503: "Authentication service unavailable",
}


def _application() -> Any:
    # Contract generation never calls providers. Sentinels allow application
    # composition to validate deterministically without reading real secrets.
    os.environ.setdefault("SCHOLENS_AI_DEEPSEEK_API_KEY", "openapi-export")
    os.environ.setdefault("STRIPE_API_KEY", "sk_openapi_export")
    os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_openapi_export")
    os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "price_openapi_monthly")
    os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "price_openapi_yearly")
    from app.main import app

    return app


def public_openapi_schema() -> dict[str, Any]:
    from app.transport.http.errors import ApiErrorResponse

    schema = deepcopy(_application().openapi())
    schema["paths"] = {
        path: schema["paths"][path]
        for path in sorted(schema.get("paths", {}))
        if path.startswith(PUBLIC_PREFIX)
    }
    model_schema = ApiErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    definitions = model_schema.pop("$defs", {})
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(definitions)
    schemas["ApiErrorResponse"] = model_schema
    response_schema = {"$ref": "#/components/schemas/ApiErrorResponse"}
    for path, operations in _AUTH_FAILURES.items():
        path_item = schema.get("paths", {}).get(path)
        if not path_item:
            continue
        for method, statuses in operations.items():
            operation = path_item.get(method)
            if not operation:
                continue
            responses = operation.setdefault("responses", {})
            for status in statuses:
                responses[str(status)] = {
                    "description": _STATUS_DESCRIPTIONS[status],
                    "content": {"application/json": {"schema": response_schema}},
                }
    return cast(dict[str, Any], schema)


def route_surface() -> dict[str, Any]:
    application_schema = _application().openapi()
    return cast(
        dict[str, Any],
        {
            "info": {
                "title": application_schema["info"]["title"],
                "version": application_schema["info"]["version"],
            },
            "paths": {
                path: sorted(
                    method
                    for method in operations
                    if method in {"get", "post", "put", "patch", "delete"}
                )
                for path, operations in sorted(application_schema["paths"].items())
            },
        },
    )


def encoded_artifacts() -> dict[Path, str]:
    return {
        OUTPUT: json.dumps(public_openapi_schema(), indent=2, sort_keys=True) + "\n",
        SURFACE_OUTPUT: json.dumps(route_surface(), indent=2, sort_keys=True) + "\n",
    }


def export_contract() -> tuple[Path, ...]:
    artifacts = encoded_artifacts()
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tuple(artifacts)


def check_contract() -> tuple[Path, ...]:
    mismatches = tuple(
        path
        for path, expected in encoded_artifacts().items()
        if not path.exists() or path.read_text(encoding="utf-8") != expected
    )
    return mismatches


__all__ = [
    "OUTPUT",
    "SURFACE_OUTPUT",
    "check_contract",
    "export_contract",
    "public_openapi_schema",
    "route_surface",
]
