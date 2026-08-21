"""Helpers for safe, literal SQL pattern matching."""

from __future__ import annotations


def literal_contains_pattern(value: str) -> str:
    """Return a LIKE contains pattern with metacharacters treated literally."""

    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


__all__ = ["literal_contains_pattern"]
