"""Canonical scholarly identifier parsing."""

from __future__ import annotations

import re
from urllib.parse import unquote

_DOI_PATTERN = re.compile(r'10\.\d{4,}/[^\s"<>]+', re.IGNORECASE)


def extract_doi(value: str) -> str | None:
    """Extract a bare DOI from DOI URLs and free-form identifier values."""
    match = _DOI_PATTERN.search(unquote(value))
    if match is None:
        return None
    return match.group(0).rstrip(".,;:)").lower()


def normalize_doi(raw: str | None) -> str | None:
    """Normalize a valid DOI to a lowercase bare identifier."""
    if not raw or not (value := raw.strip()):
        return None
    extracted = extract_doi(value)
    if extracted is not None:
        return extracted
    if value.casefold().startswith("doi:"):
        value = value[4:].strip()
    if _DOI_PATTERN.fullmatch(value):
        return value.rstrip(".,;:)").lower()
    return None


__all__ = ["extract_doi", "normalize_doi"]
