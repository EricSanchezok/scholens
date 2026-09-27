"""Complete, bounded token projections carried by immutable job results.

Vectors use the existing checked float32 format instead of large JSON float
arrays. Spans reference canonical Unicode character offsets; readers derive
text and line numbers from the exact source, never from worker-supplied copies.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scholens_ai.passages import (
    MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES,
    decode_passage_embedding_artifact,
)
from scholens_ai.token_passages import MAX_TOKEN_PASSAGES, TOKEN_WINDOW


class TokenSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    tokens: int = Field(ge=1, le=TOKEN_WINDOW)


@dataclass(frozen=True, slots=True)
class ProjectedTokenPassage:
    ordinal: int
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int
    token_count: int
    content: str
    source_digest: str
    embedding: tuple[float, ...]


class TokenProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_revision: str = Field(min_length=1, max_length=128)
    chunk_revision: Literal["tokens256-overlap32-paragraphs-v1"] = (
        "tokens256-overlap32-paragraphs-v1"
    )
    spans: list[TokenSpan] = Field(max_length=MAX_TOKEN_PASSAGES)
    vectors: str = Field(
        max_length=4 * ((MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES + 2) // 3)
    )

    def validated_passages(self, raw_content: str) -> tuple[ProjectedTokenPassage, ...]:
        if hashlib.sha256(raw_content.encode()).hexdigest() != self.content_digest:
            raise ValueError("token_projection_source_changed")
        artifact = decode_passage_embedding_artifact(
            base64.b64decode(self.vectors, validate=True)
        )
        if artifact.model_revision != self.model_revision:
            raise ValueError("token_projection_model_mismatch")
        embeddings = {
            record.source_digest: record.embedding for record in artifact.records
        }
        rows: list[ProjectedTokenPassage] = []
        used: set[str] = set()
        previous_start, covered, line = -1, 0, 1
        for ordinal, span in enumerate(self.spans):
            if not previous_start < span.start < span.end <= len(raw_content):
                raise ValueError("token_projection_offsets_invalid")
            if span.end <= covered or raw_content[covered : span.start].strip():
                raise ValueError("token_projection_coverage_invalid")
            content = raw_content[span.start : span.end]
            digest = hashlib.sha256(content.encode()).hexdigest()
            if digest not in embeddings:
                raise ValueError("token_projection_vector_missing")
            line += raw_content.count("\n", max(0, previous_start), span.start)
            rows.append(
                ProjectedTokenPassage(
                    ordinal=ordinal,
                    start_offset=span.start,
                    end_offset=span.end,
                    start_line=line,
                    end_line=line + content.count("\n"),
                    token_count=span.tokens,
                    content=content,
                    source_digest=digest,
                    embedding=embeddings[digest],
                )
            )
            used.add(digest)
            previous_start, covered = span.start, span.end
        if raw_content[covered:].strip() or used != set(embeddings):
            raise ValueError("token_projection_incomplete")
        return tuple(rows)
