"""Lossless UTF-8 paging for bounded JSON document tools."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
import hashlib
import json

from app.shared.application.json_values import normalize_json_value
from app.tooling.bounded_singleflight_lru import BoundedSingleflightLru

MAX_JSON_DOCUMENT_UTF8_BYTES = 64 * 1024 * 1024
JSON_DOCUMENT_CACHE_TOTAL_UTF8_BYTES = 128 * 1024 * 1024
JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR = 4


class JsonDocumentTooLargeError(ValueError):
    def __init__(self, *, actual_utf8_bytes: int, maximum_utf8_bytes: int) -> None:
        super().__init__(
            f"JSON document is {actual_utf8_bytes} UTF-8 bytes; "
            f"maximum is {maximum_utf8_bytes}"
        )
        self.actual_utf8_bytes = actual_utf8_bytes
        self.maximum_utf8_bytes = maximum_utf8_bytes


@dataclass(frozen=True, slots=True)
class JsonDocumentPage:
    """One code-point-safe byte range from a canonical JSON document."""

    content: str
    content_sha256: str
    start_utf8_byte: int
    end_utf8_byte: int
    total_utf8_bytes: int

    @property
    def complete(self) -> bool:
        return self.end_utf8_byte == self.total_utf8_bytes


class JsonDocumentPager:
    """Serialize once and expose exact, concatenable UTF-8 byte ranges."""

    def __init__(self, value: object) -> None:
        normalized = normalize_json_value(value)
        self._encoded = json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self._digest = hashlib.sha256(self._encoded).hexdigest()

    @property
    def content_sha256(self) -> str:
        return self._digest

    @property
    def total_utf8_bytes(self) -> int:
        return len(self._encoded)

    def page(self, *, start_utf8_byte: int, max_utf8_bytes: int) -> JsonDocumentPage:
        if start_utf8_byte < 0 or start_utf8_byte > len(self._encoded):
            raise ValueError("JSON page offset is outside the document")
        if max_utf8_bytes < 4:
            raise ValueError("JSON page size must fit one UTF-8 code point")
        if start_utf8_byte < len(self._encoded) and self._is_continuation_byte(
            self._encoded[start_utf8_byte]
        ):
            raise ValueError("JSON page offset splits a UTF-8 code point")

        end = min(len(self._encoded), start_utf8_byte + max_utf8_bytes)
        while (
            end > start_utf8_byte
            and end < len(self._encoded)
            and self._is_continuation_byte(self._encoded[end])
        ):
            end -= 1
        content = self._encoded[start_utf8_byte:end].decode("utf-8")
        return JsonDocumentPage(
            content=content,
            content_sha256=self._digest,
            start_utf8_byte=start_utf8_byte,
            end_utf8_byte=end,
            total_utf8_bytes=len(self._encoded),
        )

    @staticmethod
    def _is_continuation_byte(value: int) -> bool:
        return value & 0b1100_0000 == 0b1000_0000


class JsonDocumentPagerCache:
    """Small revision-keyed LRU for multi-call lossless document reads.

    Signed page cursors are stateless, but serializing the same large immutable
    revision on every page would make a complete read quadratic in document
    size. The owning handler supplies an actor/resource/revision key; this cache
    retains only bounded canonical byte strings and never caches signed URLs.
    """

    def __init__(
        self,
        *,
        max_entries: int = 16,
        max_total_utf8_bytes: int = JSON_DOCUMENT_CACHE_TOTAL_UTF8_BYTES,
        max_entry_utf8_bytes: int = MAX_JSON_DOCUMENT_UTF8_BYTES,
        max_concurrent_builds: int = 2,
        max_total_build_working_bytes: int | None = None,
    ) -> None:
        working_size_per_build = (
            JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR * max_entry_utf8_bytes
        )
        self._cache = BoundedSingleflightLru[JsonDocumentPager](
            max_entries=max_entries,
            max_total_size=max_total_utf8_bytes,
            max_entry_size=max_entry_utf8_bytes,
            max_concurrent_builds=max_concurrent_builds,
            size_of=lambda pager: pager.total_utf8_bytes,
            oversized=lambda actual, maximum: JsonDocumentTooLargeError(
                actual_utf8_bytes=actual,
                maximum_utf8_bytes=maximum,
            ),
            working_size_per_build=working_size_per_build,
            max_total_working_size=(
                working_size_per_build
                if max_total_build_working_bytes is None
                else max_total_build_working_bytes
            ),
        )

    @property
    def max_entry_utf8_bytes(self) -> int:
        return self._cache.max_entry_size

    @property
    def total_utf8_bytes(self) -> int:
        return self._cache.total_size

    @property
    def inflight_reserved_utf8_bytes(self) -> int:
        return self._cache.inflight_reserved_size

    @property
    def inflight_working_bytes(self) -> int:
        return self._cache.inflight_working_reserved_size

    @property
    def max_inflight_working_bytes(self) -> int:
        return self._cache.max_inflight_working_size

    @property
    def active_builds(self) -> int:
        return self._cache.active_builds

    def get_or_create(
        self,
        *,
        key: Hashable,
        value_factory: Callable[[], object],
    ) -> JsonDocumentPager:
        return self._cache.get_or_create(
            key=key,
            value_factory=lambda: JsonDocumentPager(value_factory()),
        )


__all__ = [
    "JSON_DOCUMENT_CACHE_TOTAL_UTF8_BYTES",
    "JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR",
    "MAX_JSON_DOCUMENT_UTF8_BYTES",
    "JsonDocumentPage",
    "JsonDocumentPager",
    "JsonDocumentPagerCache",
    "JsonDocumentTooLargeError",
]
