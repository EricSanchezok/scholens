"""Authentication and replay protection for Jobs -> Server requests."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import TypeVar

from scholens_job_contracts import MAX_JOBS_CALLBACK_BODY_BYTES

from app.bootstrap.container import build_job_callback_protection
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.shared.domain import AppError, FailureKind
from app.transport.http.internal_v1.references import job_delivery_reference
from app.transport.http.observability import ensure_request_id
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, TypeAdapter, ValidationError


_CallbackModel = TypeVar("_CallbackModel", bound=BaseModel)
_CALLBACK_OBJECT = TypeAdapter(dict[str, object])


def _declared_body_size(request: Request) -> int | None:
    value = request.headers.get("content-length")
    if value is None:
        return None
    try:
        size = int(value)
    except ValueError as exc:
        raise AppError(
            code="jobs_callback_size_invalid",
            message="Jobs callback Content-Length is invalid",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from exc
    if size < 0:
        raise AppError(
            code="jobs_callback_size_invalid",
            message="Jobs callback Content-Length is invalid",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    return size


def _require_bounded_callback_size(size: int) -> None:
    if size > MAX_JOBS_CALLBACK_BODY_BYTES:
        raise AppError(
            code="jobs_callback_too_large",
            message="Jobs callback exceeds the accepted body size",
            kind=FailureKind.PAYLOAD_TOO_LARGE,
            details={"max_bytes": MAX_JOBS_CALLBACK_BODY_BYTES},
        )


async def _read_bounded_callback_body(request: Request) -> bytes:
    chunks = bytearray()
    async for chunk in request.stream():
        _require_bounded_callback_size(len(chunks) + len(chunk))
        chunks.extend(chunk)
    body = bytes(chunks)
    # Preserve the bounded bytes for the route's post-authentication parser.
    # No callback route declares a FastAPI body field: doing so would make
    # FastAPI consume the unbounded request before this dependency executes.
    request._body = body
    request.state.verified_jobs_callback_body = body
    return body


def _validation_error(error: ValidationError, *, body: bytes) -> RequestValidationError:
    errors = []
    for item in error.errors():
        normalized = dict(item)
        normalized["loc"] = ("body", *item.get("loc", ()))
        errors.append(normalized)
    return RequestValidationError(errors, body=body)


def _verified_callback_body(request: Request) -> bytes:
    body = getattr(request.state, "verified_jobs_callback_body", None)
    if not isinstance(body, bytes):
        raise RuntimeError("Jobs callback body was not verified")
    return body


def parse_callback_model(
    request: Request,
    model: type[_CallbackModel],
) -> _CallbackModel:
    """Parse only the bounded bytes authenticated by ``verify_jobs_webhook``."""

    body = _verified_callback_body(request)
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise _validation_error(exc, body=body) from exc


def parse_callback_object(request: Request) -> dict[str, object]:
    """Parse an authenticated generic completion payload as a JSON object."""

    body = _verified_callback_body(request)
    try:
        return _CALLBACK_OBJECT.validate_json(body)
    except ValidationError as exc:
        raise _validation_error(exc, body=body) from exc


async def verify_jobs_webhook(
    request: Request,
) -> VerifiedJobCallback:
    secret = os.getenv("JOBS_WEBHOOK_SIGNING_SECRET")
    if not secret or len(secret.encode()) < 32:
        raise AppError(
            code="jobs_webhook_not_configured",
            message="Jobs callback authentication is unavailable",
            kind=FailureKind.UNAVAILABLE,
        )

    timestamp = request.headers.get("X-Jobs-Timestamp", "")
    nonce = request.headers.get("X-Jobs-Nonce", "")
    signature = request.headers.get("X-Jobs-Signature", "")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise AppError(
            code="invalid_jobs_signature",
            message="Jobs callback signature is invalid",
            kind=FailureKind.UNAUTHENTICATED,
        ) from exc

    if abs(int(time.time()) - timestamp_value) > 300 or not nonce or len(nonce) > 64:
        raise AppError(
            code="expired_jobs_signature",
            message="Jobs callback signature has expired",
            kind=FailureKind.UNAUTHENTICATED,
        )

    declared_size = _declared_body_size(request)
    if declared_size is not None:
        _require_bounded_callback_size(declared_size)
    body = await _read_bounded_callback_body(request)
    query = request.url.query
    target = request.url.path + (f"?{query}" if query else "")
    canonical = "\n".join(
        (
            timestamp,
            nonce,
            request.method.upper(),
            target,
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AppError(
            code="invalid_jobs_signature",
            message="Jobs callback signature is invalid",
            kind=FailureKind.UNAUTHENTICATED,
        )

    if not build_job_callback_protection().reserve_nonce(nonce):
        raise AppError(
            code="jobs_webhook_replayed",
            message="Jobs callback nonce has already been used",
            kind=FailureKind.CONFLICT,
        )
    return VerifiedJobCallback(
        request_id=ensure_request_id(request),
        delivery_ref=job_delivery_reference(nonce),
    )
