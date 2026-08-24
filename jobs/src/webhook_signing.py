"""HMAC signing for Jobs -> Server requests."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from scholens_job_contracts import (
    callback_json_bytes,
    require_callback_body_size,
)
from scholens_runtime_contracts import resolve_internal_callback_base_url

DEFAULT_WEBHOOK_BASE_URL = "http://127.0.0.1:7301"


class CallbackPayloadTooLarge(RuntimeError):
    """A callback exceeded the byte contract shared with Server."""

    error_code = "jobs_callback_too_large"


class CallbackPayloadInvalid(RuntimeError):
    """A callback could not be encoded as strict JSON."""

    error_code = "jobs_callback_invalid"


def callback_base_url() -> str:
    """Resolve the one validated internal Server authority for this runtime."""
    return resolve_internal_callback_base_url(
        configured_url=os.getenv("WEBHOOK_BASE_URL"),
        environment=os.getenv("ENVIRONMENT", "development"),
        fallback_url=DEFAULT_WEBHOOK_BASE_URL,
    )


def _production_callback_url(url: str) -> str:
    """Pin signed production callbacks to the worker's validated Server base."""
    if os.getenv("ENVIRONMENT", "development").casefold() != "production":
        return url
    base_url = callback_base_url()
    parsed = urlsplit(url)
    if (
        not parsed.path.startswith("/internal/v1/")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise RuntimeError("invalid_internal_callback_url")
    base = urlsplit(base_url)
    return urlunsplit((base.scheme, base.netloc, parsed.path, parsed.query, ""))


def _secret() -> bytes:
    value = os.getenv("JOBS_WEBHOOK_SIGNING_SECRET")
    if not value or len(value.encode()) < 32:
        raise RuntimeError("JOBS_WEBHOOK_SIGNING_SECRET is required")
    return value.encode()


def post_signed_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> requests.Response:
    url = _production_callback_url(url)
    try:
        body = encode_json_body(payload)
    except ValueError as exc:
        raise CallbackPayloadInvalid("jobs_callback_invalid") from exc
    try:
        require_callback_body_size(body)
    except ValueError as exc:
        raise CallbackPayloadTooLarge(str(exc)) from exc
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    parsed = urlsplit(url)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((timestamp, nonce, "POST", target, body_hash)).encode()
    signature = hmac.new(_secret(), canonical, hashlib.sha256).hexdigest()
    return requests.post(
        url,
        data=body,
        timeout=timeout,
        headers={
            "Content-Type": "application/json",
            "X-Jobs-Timestamp": timestamp,
            "X-Jobs-Nonce": nonce,
            "X-Jobs-Signature": signature,
        },
    )


def encode_json_body(payload: dict[str, Any] | None) -> bytes:
    return callback_json_bytes(payload) if payload is not None else b""
