"""Transport-neutral paper reading and evidence-search capabilities."""

from __future__ import annotations

import re as stdlib_re
from collections.abc import Iterator
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from uuid import UUID

import regex
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import AppError, FailureKind

PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS = 0.5
PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES = 1_024
PAPER_CONTENT_SEARCH_MATCH_SOURCE_CHARACTERS = 1_024
_LINE_BREAK = stdlib_re.compile(r"\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]")


@dataclass(frozen=True)
class AccessiblePaperContent:
    document_id: UUID
    original_filename: str
    title: str | None
    abstract: str | None
    raw_content: str | None
    storage_key: str
    parser_markdown_storage_key: str | None
    content_revision: str


@dataclass(frozen=True, slots=True)
class PaperContentRevision:
    """Lightweight authorization result for one canonical document revision."""

    document_id: UUID
    revision: str
    retained_size_upper_bound: int | None = None


@dataclass(frozen=True, slots=True)
class AccessiblePaperContentPreview:
    """A database-bounded prefix plus scalar facts about the full text."""

    document_id: UUID
    revision: str
    content: str | None
    total_lines: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class PaperContentSearchPage:
    """One bounded regex-search page over an immutable content digest."""

    matches: tuple[str, ...]
    content_sha256: str
    next_offset: int | None
    next_line: int | None


class PaperContentPort(Protocol):
    def get_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperContentRevision | None: ...

    def get_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperContentRevision | None: ...

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent | None: ...

    def get_snapshot(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent | None: ...

    def get_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        max_characters: int,
    ) -> AccessiblePaperContentPreview | None: ...


class PaperContentCapabilities:
    """One business capability shared by HTTP, Agent, and future MCP adapters."""

    def __init__(
        self,
        content: PaperContentPort,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._content = content
        self._project_documents = project_documents

    def authorize_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperContentRevision:
        """Revalidate access without hydrating the potentially large paper text."""

        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        revision = self._content.get_revision(
            actor=actor,
            document_id=document_id,
        )
        if revision is None:
            raise _paper_not_found()
        return revision

    def authorize_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperContentRevision:
        """Calculate a retained-size bound only for a cache miss."""

        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        revision = self._content.get_retained_size(
            actor=actor,
            document_id=document_id,
        )
        if revision is None:
            raise _paper_not_found()
        return revision

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> AccessiblePaperContent:
        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        paper = self._content.get(
            actor=actor,
            document_id=document_id,
        )
        if paper is None:
            raise _paper_not_found()
        return paper

    def read_snapshot(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> AccessiblePaperContent:
        """Hydrate only fields retained by the bounded paging snapshot."""

        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        paper = self._content.get_snapshot(actor=actor, document_id=document_id)
        if paper is None:
            raise _paper_not_found()
        return paper

    def read_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        max_characters: int,
        project_id: UUID | None = None,
    ) -> AccessiblePaperContentPreview:
        """Read a bounded prefix without hydrating the canonical full text."""

        if not 1 <= max_characters <= 64 * 1024:
            raise ValueError("paper preview character limit is outside its safe bound")
        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        preview = self._content.get_preview(
            actor=actor,
            document_id=document_id,
            max_characters=max_characters,
        )
        if preview is None:
            raise _paper_not_found()
        return preview

    def _require_project_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> None:
        if project_id is not None and document_id not in self._project_documents(
            actor=actor,
            project_id=project_id,
        ):
            raise _paper_not_found()

    def search_content(
        self,
        *,
        content: str | None,
        content_sha256: str | None,
        query: str,
        start_offset: int = 0,
        start_line: int = 1,
        expected_content_sha256: str | None = None,
        limit: int = 10,
    ) -> PaperContentSearchPage:
        """Search an already authorized immutable snapshot without rehashing it."""

        if not content:
            raise AppError(
                code="paper_content_not_available",
                message="Extracted paper text is not available",
                kind=FailureKind.UNPROCESSABLE,
            )
        if (
            isinstance(limit, bool)
            or not 1 <= limit <= 20
            or start_offset < 0
            or start_offset > len(content)
            or start_line < 1
        ):
            raise AppError(
                code="paper_content_search_cursor_invalid",
                message="The paper-content search cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if content_sha256 is None:
            raise ValueError("available paper content requires a stable digest")
        if (
            expected_content_sha256 is not None
            and expected_content_sha256 != content_sha256
        ):
            raise AppError(
                code="paper_content_search_cursor_invalid",
                message="The paper content changed after the previous search page",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        try:
            pattern = regex.compile(query, regex.IGNORECASE)
        except regex.error as exc:
            raise AppError(
                code="paper_content_search_pattern_invalid",
                message="The paper-content search pattern is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc

        deadline = monotonic() + PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS
        matches: list[str] = []
        made_progress = False
        for line_offset, line_number, line_end in _iter_line_spans(
            content,
            start_offset=start_offset,
            start_line=start_line,
        ):
            remaining = deadline - monotonic()
            if remaining <= 0:
                if not made_progress:
                    raise _search_too_complex()
                return PaperContentSearchPage(
                    matches=tuple(matches),
                    content_sha256=content_sha256,
                    next_offset=line_offset,
                    next_line=line_number,
                )
            try:
                matched = (
                    pattern.search(
                        content,
                        line_offset,
                        line_end,
                        timeout=remaining,
                    )
                    is not None
                )
            except TimeoutError as exc:
                raise _search_too_complex() from exc
            made_progress = True
            if not matched:
                continue
            if len(matches) == limit:
                return PaperContentSearchPage(
                    matches=tuple(matches),
                    content_sha256=content_sha256,
                    next_offset=line_offset,
                    next_line=line_number,
                )
            matches.append(
                _bounded_match(
                    line_number=line_number,
                    content=content,
                    line_start=line_offset,
                    line_end=line_end,
                )
            )
        return PaperContentSearchPage(
            matches=tuple(matches),
            content_sha256=content_sha256,
            next_offset=None,
            next_line=None,
        )


def _iter_line_spans(
    value: str,
    *,
    start_offset: int,
    start_line: int,
) -> Iterator[tuple[int, int, int]]:
    """Return line spans from a signed cursor without copying the line text."""

    offset = start_offset
    line_number = start_line
    while offset < len(value):
        separator = _LINE_BREAK.search(value, offset)
        if separator is None:
            yield offset, line_number, len(value)
            return
        yield offset, line_number, separator.start()
        offset = separator.end()
        line_number += 1


def _bounded_match(
    *,
    line_number: int,
    content: str,
    line_start: int,
    line_end: int,
) -> str:
    preview_end = min(
        line_end,
        line_start + PAPER_CONTENT_SEARCH_MATCH_SOURCE_CHARACTERS,
    )
    value = f"{line_number}: {content[line_start:preview_end]}"
    bounded = json_bounded_prefix(
        value,
        max_bytes=PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES,
    )
    if bounded == value and preview_end == line_end:
        return bounded
    return (
        json_bounded_prefix(
            bounded,
            max_bytes=PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES - 5,
        ).rstrip()
        + "…"
    )


def _search_too_complex() -> AppError:
    return AppError(
        code="paper_content_search_too_complex",
        message="The paper-content search pattern exceeded its safe time budget",
        kind=FailureKind.INVALID_ARGUMENT,
    )


def _paper_not_found() -> AppError:
    return AppError(
        code="paper_not_found",
        message="Paper not found",
        kind=FailureKind.NOT_FOUND,
    )


__all__ = [
    "AccessiblePaperContent",
    "AccessiblePaperContentPreview",
    "PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES",
    "PAPER_CONTENT_SEARCH_MATCH_SOURCE_CHARACTERS",
    "PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS",
    "PaperContentCapabilities",
    "PaperContentPort",
    "PaperContentRevision",
    "PaperContentSearchPage",
]
