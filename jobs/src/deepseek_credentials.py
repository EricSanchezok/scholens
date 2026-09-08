"""Fetch a credential only inside a claimed, signed job scope."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from src.webhook_signing import post_signed_json

_credential_url: ContextVar[str | None] = ContextVar(
    "deepseek_job_credential_url", default=None
)


class DeepSeekCredentialRequired(RuntimeError):
    """The task owner needs to connect DeepSeek."""


@contextmanager
def deepseek_job_context(webhook_url: str) -> Iterator[None]:
    token = _credential_url.set(
        webhook_url.rsplit("/", 1)[0] + "/integration-credentials/deepseek"
    )
    try:
        yield
    finally:
        _credential_url.reset(token)


def _fetch_key(url: str) -> str:
    response = post_signed_json(url, {}, timeout=30)
    try:
        if response.status_code in {409, 422}:
            error = response.json()
            if isinstance(error, dict) and error.get("code") in {
                "deepseek_credential_required",
                "deepseek_credential_invalid",
            }:
                raise DeepSeekCredentialRequired(
                    "Connect your DeepSeek API key in Settings"
                )
        if response.status_code >= 400:
            raise RuntimeError("Job-scoped DeepSeek credentials are unavailable")
        payload = response.json()
        key = payload.get("credential")
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError("Invalid job credential response")
        return key
    finally:
        response.close()


async def current_deepseek_key() -> str:
    url = _credential_url.get()
    if url is None:
        raise DeepSeekCredentialRequired("A claimed job credential scope is required")
    return await asyncio.to_thread(_fetch_key, url)
