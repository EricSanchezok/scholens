"""Bounded token windows with exact canonical character and line coordinates."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import re
from typing import Protocol
import os
from pathlib import Path

from tokenizers import Tokenizer
from scholens_ai.model_artifacts import TOKENIZER_SHA256, file_sha256

TOKEN_PASSAGE_REVISION = "tokens256-overlap32-paragraphs-v1"
TOKEN_WINDOW = 256
TOKEN_OVERLAP = 32
TOKEN_LOOKAHEAD_CHARACTERS = 8192
MAX_TOKEN_PASSAGES = 10_000
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


class EncodedOffsets(Protocol):
    @property
    def offsets(self) -> list[tuple[int, int]]: ...


class OffsetTokenizer(Protocol):
    def encode(self, sequence: str, *, add_special_tokens: bool) -> EncodedOffsets: ...


class PassageLimitExceeded(ValueError):
    """Keep the previous projection; never label a truncated index complete."""


def load_passage_tokenizer(model_dir: str | Path | None = None) -> Tokenizer:
    """Load only the pinned tokenizer; index clients never need private weights."""
    configured = model_dir or os.getenv("SCHOLENS_EMBEDDING_MODEL_PATH")
    if not configured:
        raise RuntimeError("SCHOLENS_EMBEDDING_MODEL_PATH is not configured")
    path = Path(configured) / "tokenizer.json"
    if file_sha256(path) != TOKENIZER_SHA256:
        raise ValueError("Token passage tokenizer digest mismatch")
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    return tokenizer


@dataclass(frozen=True, slots=True)
class TokenPassage:
    ordinal: int
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int
    token_count: int
    content: str

    @property
    def source_digest(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    @property
    def identity(self) -> str:
        value = f"{TOKEN_PASSAGE_REVISION}:{self.start_offset}:{self.end_offset}:{self.source_digest}"
        return hashlib.sha256(value.encode()).hexdigest()


def iter_token_passages(
    raw_content: str,
    tokenizer: OffsetTokenizer,
    *,
    limit: int = MAX_TOKEN_PASSAGES,
) -> Iterator[TokenPassage]:
    """Tokenize a small rolling buffer, never an entire large document at once.

    Offsets always refer to the unchanged input. The caller supplies a tokenizer
    with truncation and padding disabled. Existing five-line projections remain
    independent until the versioned replacement is completely built.
    """
    if not 1 <= limit <= MAX_TOKEN_PASSAGES:
        raise ValueError("Invalid passage count bound")
    cursor, ordinal, previous_start, line = 0, 0, 0, 1
    while cursor < len(raw_content):
        segment = raw_content[cursor : cursor + TOKEN_LOOKAHEAD_CHARACTERS]
        offsets = [
            (start, end)
            for start, end in tokenizer.encode(
                segment, add_special_tokens=False
            ).offsets
            if end > start
        ]
        if not offsets:
            cursor += len(segment)
            continue
        count = min(TOKEN_WINDOW, len(offsets))
        ends = [end for _start, end in offsets[:count]]
        if count == TOKEN_WINDOW:
            for boundary in _PARAGRAPH_BREAK.finditer(segment[: ends[-1]]):
                candidate = bisect_right(ends, boundary.start())
                if candidate >= TOKEN_WINDOW // 2:
                    count = candidate
        start, end = offsets[0][0], offsets[count - 1][1]
        # Re-encoding a substring can add a boundary token for some tokenizers.
        # Enforce the actual model input bound, not an estimated character ratio.
        actual = tokenizer.encode(segment[start:end], add_special_tokens=False).offsets
        while len(actual) > TOKEN_WINDOW:
            bounded_end = start + actual[TOKEN_WINDOW - 1][1]
            if bounded_end >= end:
                # Several byte-fallback tokens can describe one Unicode
                # character. Its end still includes the overflowing tokens;
                # exclude that whole character rather than cutting a token.
                bounded_end = start + actual[TOKEN_WINDOW][0]
            if not start < bounded_end < end:
                raise ValueError("Tokenizer cannot produce a bounded canonical passage")
            end = bounded_end
            count = bisect_right([value[1] for value in offsets], end)
            actual = tokenizer.encode(
                segment[start:end], add_special_tokens=False
            ).offsets
        if not actual or len(actual) > TOKEN_WINDOW or end <= start:
            raise ValueError("Tokenizer cannot produce a bounded canonical passage")
        if ordinal >= limit:
            raise PassageLimitExceeded("Token passage limit exceeded")
        absolute_start, absolute_end = cursor + start, cursor + end
        line += raw_content.count("\n", previous_start, absolute_start)
        content = raw_content[absolute_start:absolute_end]
        yield TokenPassage(
            ordinal=ordinal,
            start_offset=absolute_start,
            end_offset=absolute_end,
            start_line=line,
            end_line=line + content.count("\n"),
            token_count=len(actual),
            content=content,
        )
        ordinal += 1
        previous_start = absolute_start
        if count == len(offsets) and cursor + len(segment) == len(raw_content):
            break
        overlap_start = (
            offsets[count - TOKEN_OVERLAP][0] if count > TOKEN_OVERLAP else end
        )
        next_cursor = cursor + overlap_start
        if next_cursor <= cursor:
            raise ValueError("Tokenizer failed to advance its canonical offset")
        cursor = next_cursor
