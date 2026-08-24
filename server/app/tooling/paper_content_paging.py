"""Lossless, revision-cached paging for extracted paper text."""

from __future__ import annotations

import bisect
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import re
import sys
from threading import BoundedSemaphore
from uuid import UUID

from app.modules.papers.application.content import (
    AccessiblePaperContent,
    PaperContentCapabilities,
)
from app.shared.application import Actor
from app.shared.application.json_values import JsonNormalizationError
from app.shared.application.text import json_bounded_prefix, utf8_prefix
from app.shared.domain import AppError, FailureKind
from app.tooling.bounded_singleflight_lru import BoundedSingleflightLru

DEFAULT_PAPER_CONTENT_UTF8_BYTES = 32 * 1024
MAX_PAPER_CONTENT_UTF8_BYTES = 32 * 1024
PAPER_CONTENT_JSON_STRING_BYTES = 12 * 1024
PAPER_CONTENT_SOURCE_UTF8_BYTES = 8 * 1024
PAPER_CONTENT_OUTPUT_BYTES = 80 * 1024

PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL = 256
MAX_PAPER_CONTENT_CACHE_ENTRY_RETAINED_BYTES = 64 * 1024 * 1024
PAPER_CONTENT_CACHE_TOTAL_RETAINED_BYTES = 128 * 1024 * 1024
# Covers the temporary checkpoint-list slots plus one Unicode hash slice and
# its encoded chunk at the maximum accepted retained-size preflight.
PAPER_CONTENT_BUILD_WORKING_BYTES = 2 * 1024 * 1024
PAPER_CONTENT_SEARCH_MAX_CONCURRENCY = 2
_PAPER_CONTENT_HASH_CHUNK_CHARACTERS = 64 * 1024

_LINE_BREAK = re.compile(r"\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]")


class PaperContentSnapshotTooLargeError(ValueError):
    def __init__(
        self, *, actual_retained_bytes: int, maximum_retained_bytes: int
    ) -> None:
        super().__init__(
            f"paper content snapshot retains {actual_retained_bytes} bytes; "
            f"maximum is {maximum_retained_bytes}"
        )
        self.actual_retained_bytes = actual_retained_bytes
        self.maximum_retained_bytes = maximum_retained_bytes


class PaperContentSearchCapacityError(RuntimeError):
    """The process-wide bounded paper-search slots are currently occupied."""


@dataclass(frozen=True, slots=True)
class PaperContentPage:
    content: str
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int | None
    total_lines: int
    starts_mid_line: bool
    ends_mid_line: bool
    next_offset: int | None
    next_start_line: int | None


@dataclass(frozen=True, slots=True)
class PaperContentPager:
    """One immutable digest plus a sparse line index for bounded page reads."""

    raw_content: str
    line_checkpoints: tuple[int, ...]
    total_lines: int
    content_sha256: str
    retained_size_bytes: int

    @classmethod
    def build(cls, raw_content: str) -> PaperContentPager:
        checkpoints: list[int] = [0] if raw_content else []
        total_lines = 1 if raw_content else 0
        for separator in _LINE_BREAK.finditer(raw_content):
            if separator.end() == len(raw_content):
                continue
            total_lines += 1
            if (total_lines - 1) % PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL == 0:
                checkpoints.append(separator.end())
        checkpoint_tuple = tuple(checkpoints)
        content_sha256 = _bounded_utf8_sha256(raw_content)
        retained_size_bytes = (
            sys.getsizeof(raw_content)
            + sys.getsizeof(checkpoint_tuple)
            + sum(sys.getsizeof(offset) for offset in checkpoint_tuple)
            + sys.getsizeof(content_sha256)
        )
        return cls(
            raw_content=raw_content,
            line_checkpoints=checkpoint_tuple,
            total_lines=total_lines,
            content_sha256=content_sha256,
            retained_size_bytes=retained_size_bytes,
        )

    def offset_for_line(self, line_number: int) -> int:
        if line_number < 1 or line_number > self.total_lines:
            raise ValueError("line number is outside the extracted text")
        checkpoint_index = (line_number - 1) // PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL
        offset = self.line_checkpoints[checkpoint_index]
        current_line = checkpoint_index * PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL + 1
        for separator in _LINE_BREAK.finditer(self.raw_content, offset):
            if current_line == line_number:
                break
            offset = separator.end()
            current_line += 1
        return offset

    def page(
        self,
        *,
        offset: int,
        max_lines: int,
        max_utf8_bytes: int,
        start_line: int | None = None,
    ) -> PaperContentPage:
        if max_lines < 1 or max_utf8_bytes < 4:
            raise ValueError("page limits must be positive")
        if not self.raw_content:
            if offset != 0 or start_line not in (None, 1):
                raise ValueError("offset is outside the extracted text")
            return PaperContentPage(
                content="",
                start_offset=0,
                end_offset=0,
                start_line=1,
                end_line=None,
                total_lines=0,
                starts_mid_line=False,
                ends_mid_line=False,
                next_offset=None,
                next_start_line=None,
            )
        if offset < 0 or offset >= len(self.raw_content):
            raise ValueError("offset is outside the extracted text")

        resolved_start_line = (
            self._line_number_for_offset(offset) if start_line is None else start_line
        )
        if resolved_start_line < 1 or resolved_start_line > self.total_lines:
            raise ValueError("line number is outside the extracted text")
        line_start_offset = self.offset_for_line(resolved_start_line)
        if line_start_offset > offset:
            raise ValueError("line number is inconsistent with the page offset")

        # Page output is byte-bounded, so scanning beyond the largest possible
        # character prefix would repeat work on a very long line. Include one
        # extra character on each side only to recognize a CRLF boundary.
        scan_start = max(line_start_offset, offset - 1)
        scan_end = min(len(self.raw_content), offset + max_utf8_bytes + 1)
        boundaries: list[int] = []
        line_limited_end: int | None = None
        for separator in _LINE_BREAK.finditer(
            self.raw_content,
            scan_start,
            scan_end,
        ):
            if separator.end() <= offset:
                continue
            boundaries.append(separator.end())
            if len(boundaries) == max_lines:
                line_limited_end = separator.end()
                break

        candidate_end = min(
            len(self.raw_content),
            offset + max_utf8_bytes,
            line_limited_end if line_limited_end is not None else len(self.raw_content),
        )
        byte_limited = utf8_prefix(
            self.raw_content[offset:candidate_end],
            max_bytes=max_utf8_bytes,
        )
        content = json_bounded_prefix(
            byte_limited,
            max_bytes=PAPER_CONTENT_JSON_STRING_BYTES,
        )
        if not content:
            raise ValueError("page budget cannot represent the next Unicode code point")

        end_offset = offset + len(content)
        end_line = resolved_start_line
        boundary_at_end = False
        for boundary in boundaries:
            if boundary < end_offset:
                end_line += 1
                continue
            if boundary == end_offset:
                boundary_at_end = True
            break

        next_offset = end_offset if end_offset < len(self.raw_content) else None
        next_start_line = (
            end_line + 1 if next_offset is not None and boundary_at_end else None
        )
        return PaperContentPage(
            content=content,
            start_offset=offset,
            end_offset=end_offset,
            start_line=resolved_start_line,
            end_line=end_line,
            total_lines=self.total_lines,
            starts_mid_line=offset != line_start_offset,
            ends_mid_line=end_offset < len(self.raw_content) and not boundary_at_end,
            next_offset=next_offset,
            next_start_line=next_start_line,
        )

    def _line_number_for_offset(self, offset: int) -> int:
        checkpoint_index = bisect.bisect_right(self.line_checkpoints, offset) - 1
        checkpoint_offset = self.line_checkpoints[checkpoint_index]
        line_number = checkpoint_index * PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL + 1
        for separator in _LINE_BREAK.finditer(
            self.raw_content,
            checkpoint_offset,
            offset + 1,
        ):
            if separator.end() <= offset:
                line_number += 1
        return line_number


@dataclass(frozen=True, slots=True)
class PaperContentSnapshot:
    """One cacheable, immutable content revision and its bounded metadata."""

    revision: str
    title: str | None
    content_available: bool
    pager: PaperContentPager
    retained_size_bytes: int

    @classmethod
    def build(cls, paper: AccessiblePaperContent) -> PaperContentSnapshot:
        pager = PaperContentPager.build(paper.raw_content or "")
        retained_size_bytes = (
            pager.retained_size_bytes
            + sys.getsizeof(paper.content_revision)
            + sys.getsizeof(paper.title)
        )
        return cls(
            revision=paper.content_revision,
            title=paper.title,
            content_available=paper.raw_content is not None,
            pager=pager,
            retained_size_bytes=retained_size_bytes,
        )

    @property
    def raw_content(self) -> str | None:
        return self.pager.raw_content if self.content_available else None

    @property
    def content_sha256(self) -> str | None:
        return self.pager.content_sha256 if self.content_available else None


class PaperContentSnapshotCache:
    """Thread-safe actor/revision-keyed LRU with hard retained-memory limits."""

    def __init__(
        self,
        *,
        max_entries: int = 16,
        max_total_retained_bytes: int = PAPER_CONTENT_CACHE_TOTAL_RETAINED_BYTES,
        max_entry_retained_bytes: int = MAX_PAPER_CONTENT_CACHE_ENTRY_RETAINED_BYTES,
        max_concurrent_builds: int = 2,
        max_concurrent_searches: int = PAPER_CONTENT_SEARCH_MAX_CONCURRENCY,
    ) -> None:
        if max_concurrent_searches <= 0:
            raise ValueError("max_concurrent_searches must be positive")
        self._cache = BoundedSingleflightLru[PaperContentSnapshot](
            max_entries=max_entries,
            max_total_size=max_total_retained_bytes,
            max_entry_size=max_entry_retained_bytes,
            max_concurrent_builds=max_concurrent_builds,
            size_of=lambda snapshot: snapshot.retained_size_bytes,
            oversized=lambda actual, maximum: PaperContentSnapshotTooLargeError(
                actual_retained_bytes=actual,
                maximum_retained_bytes=maximum,
            ),
            working_size_per_build=PAPER_CONTENT_BUILD_WORKING_BYTES,
        )
        self._search_slots = BoundedSemaphore(max_concurrent_searches)

    @property
    def max_entry_retained_bytes(self) -> int:
        return self._cache.max_entry_size

    @property
    def total_retained_bytes(self) -> int:
        return self._cache.total_size

    @property
    def inflight_reserved_bytes(self) -> int:
        return self._cache.inflight_reserved_size

    @property
    def inflight_working_reserved_bytes(self) -> int:
        return self._cache.inflight_working_reserved_size

    @property
    def max_inflight_working_bytes(self) -> int:
        return self._cache.max_inflight_working_size

    @property
    def active_builds(self) -> int:
        return self._cache.active_builds

    def get(self, *, key: Hashable) -> PaperContentSnapshot | None:
        return self._cache.get(key=key)

    def get_or_create(
        self,
        *,
        key: Hashable,
        value_factory: Callable[[], AccessiblePaperContent],
    ) -> PaperContentSnapshot:
        return self._cache.get_or_create(
            key=key,
            value_factory=lambda: PaperContentSnapshot.build(value_factory()),
        )

    @contextmanager
    def search_slot(self, *, timeout_seconds: float) -> Iterator[None]:
        """Bound concurrent regex scans, including scans over cache hits."""

        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must not be negative")
        if not self._search_slots.acquire(timeout=timeout_seconds):
            raise PaperContentSearchCapacityError
        try:
            yield
        finally:
            self._search_slots.release()


class _PaperContentRevisionAdvanced(RuntimeError):
    """A lightweight revision read raced one bounded hydration."""


def authorized_paper_content_snapshot(
    *,
    capability: PaperContentCapabilities,
    actor: Actor,
    document_id: UUID,
    cache: PaperContentSnapshotCache,
) -> PaperContentSnapshot:
    """Authorize, preflight, and singleflight one immutable paper revision."""

    for _attempt in range(2):
        access = capability.authorize_revision(
            actor=actor,
            document_id=document_id,
        )
        cache_key = (actor.id, document_id, access.revision)

        def hydrate() -> AccessiblePaperContent:
            sized_access = capability.authorize_retained_size(
                actor=actor,
                document_id=document_id,
            )
            if sized_access.revision != access.revision:
                raise _PaperContentRevisionAdvanced
            upper_bound = sized_access.retained_size_upper_bound
            if upper_bound is not None and upper_bound > cache.max_entry_retained_bytes:
                raise AppError(
                    code="paper_content_paging_limit_exceeded",
                    message=(
                        "The extracted paper text exceeds the supported lossless "
                        "paging cache limit"
                    ),
                    kind=FailureKind.PAYLOAD_TOO_LARGE,
                    details={
                        "retained_size_upper_bound": upper_bound,
                        "maximum_retained_bytes": cache.max_entry_retained_bytes,
                    },
                )
            paper = capability.read_snapshot(actor=actor, document_id=document_id)
            if paper.content_revision != access.revision:
                raise _PaperContentRevisionAdvanced
            return paper

        try:
            return cache.get_or_create(key=cache_key, value_factory=hydrate)
        except _PaperContentRevisionAdvanced:
            continue
        except PaperContentSnapshotTooLargeError as exc:
            raise AppError(
                code="paper_content_paging_limit_exceeded",
                message=(
                    "The extracted paper text exceeds the supported lossless "
                    "paging cache limit"
                ),
                kind=FailureKind.PAYLOAD_TOO_LARGE,
                details={
                    "actual_retained_bytes": exc.actual_retained_bytes,
                    "maximum_retained_bytes": exc.maximum_retained_bytes,
                },
            ) from exc
    raise AppError(
        code="paper_content_cursor_invalid",
        message="The paper content changed while the page was prepared",
        kind=FailureKind.CONFLICT,
    )


def _bounded_utf8_sha256(value: str) -> str:
    """Hash valid UTF-8 with a fixed-size transient allocation per build."""

    digest = hashlib.sha256()
    try:
        for start in range(0, len(value), _PAPER_CONTENT_HASH_CHUNK_CHARACTERS):
            digest.update(
                value[start : start + _PAPER_CONTENT_HASH_CHUNK_CHARACTERS].encode(
                    "utf-8"
                )
            )
    except UnicodeEncodeError as exc:
        raise JsonNormalizationError("$ contains invalid Unicode") from exc
    return digest.hexdigest()


__all__ = [
    "DEFAULT_PAPER_CONTENT_UTF8_BYTES",
    "MAX_PAPER_CONTENT_CACHE_ENTRY_RETAINED_BYTES",
    "MAX_PAPER_CONTENT_UTF8_BYTES",
    "PAPER_CONTENT_CACHE_TOTAL_RETAINED_BYTES",
    "PAPER_CONTENT_BUILD_WORKING_BYTES",
    "PAPER_CONTENT_SEARCH_MAX_CONCURRENCY",
    "PAPER_CONTENT_JSON_STRING_BYTES",
    "PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL",
    "PAPER_CONTENT_OUTPUT_BYTES",
    "PAPER_CONTENT_SOURCE_UTF8_BYTES",
    "PaperContentPage",
    "PaperContentPager",
    "PaperContentSnapshot",
    "PaperContentSnapshotCache",
    "PaperContentSearchCapacityError",
    "PaperContentSnapshotTooLargeError",
    "authorized_paper_content_snapshot",
    "json_bounded_prefix",
    "utf8_prefix",
]
