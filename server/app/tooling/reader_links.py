"""Stable browser links for authenticated Scholens Reader pages."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit
from uuid import UUID

READER_URL_MAX_LENGTH = 2_048

READER_URL_DESCRIPTION = (
    "Authenticated browser URL for reading this stored paper in Scholens. Use it "
    "as the durable user-facing Markdown link by substituting the actual returned "
    "URL, for example [Paper title](https://scholens.example/reader/<document-id>). "
    "Never emit the literal placeholder reader_url. "
    "It is null when no document is available yet."
)

READER_LINK_GUIDANCE = (
    "Use the actual returned reader_url as the durable user-facing Scholens link. "
    "When writing Markdown, notes, reports, or citations, substitute it into the "
    "link target; never emit the literal text reader_url. Keep "
    "DOI, arXiv, or source URLs as provenance only; never persist temporary "
    "file_url, preview_url, or upload URLs."
)


def normalize_web_base_url(value: str) -> str:
    """Validate and normalize the configured browser origin."""

    base = value.strip().rstrip("/")
    parsed = urlsplit(base)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("CLIENT_DOMAIN contains an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("CLIENT_DOMAIN must be an HTTP(S) origin without a path")
    return base


def build_reader_url(
    *,
    web_base_url: str,
    document_id: UUID,
    project_id: UUID | None = None,
) -> str:
    """Build a durable, authenticated Reader URL for one stored paper."""

    base = normalize_web_base_url(web_base_url)
    url = f"{base}/reader/{document_id}"
    if project_id is not None:
        url = f"{url}?{urlencode({'project': str(project_id)})}"
    if len(url) > READER_URL_MAX_LENGTH:
        raise ValueError("Reader URL exceeds its supported length")
    return url


__all__ = [
    "READER_LINK_GUIDANCE",
    "READER_URL_DESCRIPTION",
    "READER_URL_MAX_LENGTH",
    "build_reader_url",
    "normalize_web_base_url",
]
