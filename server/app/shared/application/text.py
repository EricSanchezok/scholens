"""Small UTF-8 boundary helpers shared by public projections."""

from __future__ import annotations

from app.shared.application.json_values import require_valid_json_string


def utf8_prefix(value: str, *, max_bytes: int) -> str:
    """Return the longest cheap prefix that never splits a Unicode code point."""

    require_valid_json_string(value)
    if max_bytes <= 0:
        return ""
    candidate = value[:max_bytes]
    encoded = candidate.encode("utf-8")
    if len(encoded) <= max_bytes:
        return candidate
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def json_bounded_prefix(value: str, *, max_bytes: int) -> str:
    """Return a prefix whose encoded JSON string fits the supplied byte budget."""

    require_valid_json_string(value)
    # Two bytes are reserved for the JSON string's surrounding quotation marks.
    # Counting each code point directly avoids serializing the full value, then
    # repeatedly serializing large candidate slices during a binary search.
    encoded_size = 2
    for index, character in enumerate(value):
        character_size = _json_character_size(character)
        if encoded_size + character_size > max_bytes:
            return value[:index]
        encoded_size += character_size
    return value


def _json_character_size(character: str) -> int:
    code_point = ord(character)
    if character in {'"', "\\"}:
        return 2
    if code_point < 0x20:
        return 2 if character in "\b\t\n\f\r" else 6
    if code_point <= 0x7F:
        return 1
    if code_point <= 0x7FF:
        return 2
    if code_point <= 0xFFFF:
        return 3
    return 4


__all__ = ["json_bounded_prefix", "utf8_prefix"]
