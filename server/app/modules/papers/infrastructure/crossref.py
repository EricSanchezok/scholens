"""Crossref metadata access with no application credential dependency."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import requests
from app.modules.papers.application.contracts.discovery import EnrichedData
from app.modules.papers.domain import normalize_doi

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.crossref.org"
_TIMEOUT_SECONDS = 10


class CrossrefClient:
    def find_doi(self, *, title: str, authors: list[str] | None = None) -> str | None:
        if not title:
            return None
        params: dict[str, str | int] = {"query.title": title, "rows": 1}
        if authors:
            params["query.author"] = ", ".join(authors)
        try:
            response = requests.get(
                f"{_BASE_URL}/works",
                params=params,
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("crossref.doi_lookup.failed", exc_info=True)
            return None
        message = payload.get("message") if isinstance(payload, Mapping) else None
        items = message.get("items") if isinstance(message, Mapping) else None
        if not isinstance(items, Sequence) or not items:
            return None
        top_match = items[0]
        if not isinstance(top_match, Mapping):
            return None
        titles = top_match.get("title")
        if not isinstance(titles, Sequence) or isinstance(titles, (str, bytes)):
            return None
        if title.casefold() not in {
            candidate.casefold() for candidate in titles if isinstance(candidate, str)
        }:
            return None
        doi = top_match.get("DOI")
        return normalize_doi(doi if isinstance(doi, str) else None)

    def enriched_data(self, *, doi: str) -> EnrichedData | None:
        normalized = normalize_doi(doi)
        if normalized is None:
            return None
        try:
            response = requests.get(
                f"{_BASE_URL}/works/{quote(normalized, safe='')}",
                timeout=_TIMEOUT_SECONDS,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("crossref.enrichment.failed", exc_info=True)
            return None
        message = payload.get("message") if isinstance(payload, Mapping) else None
        if not isinstance(message, Mapping):
            return None
        publisher = message.get("publisher")
        container_titles = message.get("container-title")
        journal = (
            container_titles[0]
            if isinstance(container_titles, Sequence)
            and not isinstance(container_titles, (str, bytes))
            and container_titles
            and isinstance(container_titles[0], str)
            else None
        )
        return EnrichedData(
            publisher=publisher if isinstance(publisher, str) else None,
            journal=journal,
            publication_date=_publication_date(message),
        )


def _publication_date(message: Mapping[object, object]) -> str | None:
    for key in ("published-print", "published-online"):
        publication = message.get(key)
        if not isinstance(publication, Mapping):
            continue
        date_parts = publication.get("date-parts")
        if (
            not isinstance(date_parts, Sequence)
            or isinstance(date_parts, (str, bytes))
            or not date_parts
            or not isinstance(date_parts[0], Sequence)
        ):
            continue
        parts = [part for part in date_parts[0][:3] if isinstance(part, int)]
        if len(parts) == 3:
            return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
        if len(parts) == 2:
            return f"{parts[0]:04d}-{parts[1]:02d}"
        if len(parts) == 1:
            return f"{parts[0]:04d}"
    return None


__all__ = ["CrossrefClient"]
