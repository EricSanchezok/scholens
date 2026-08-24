"""Plain-text excerpts shared by search infrastructure adapters."""

from __future__ import annotations

import re


def plain_query_excerpt(
    content: str | None,
    query: str,
    *,
    limit: int = 220,
) -> str | None:
    """Return bounded plain text, centered on a literal query when present."""

    if not content or limit <= 0:
        return None
    plain = re.sub(r"<[^>]+>", " ", content)
    plain = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[`#>*_~|]", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return None
    if limit < 3:
        return plain[:limit]
    lowered = plain.casefold()
    terms = [query.casefold(), *query.casefold().split()]
    positions = [lowered.find(term) for term in terms if term]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - 70) if positions else 0
    prefix = "…" if start > 0 else ""
    provisional_end = min(len(plain), start + limit - len(prefix))
    suffix = "…" if provisional_end < len(plain) else ""
    end = min(len(plain), start + limit - len(prefix) - len(suffix))
    return f"{prefix}{plain[start:end].strip()}{suffix}"


__all__ = ["plain_query_excerpt"]
