"""Bounded, data-only protocol for one host's private inference socket."""

from __future__ import annotations

import math
import struct
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scholens_ai.embeddings import EMBEDDING_DIMENSION

FRAME_HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 256 * 1024
MAX_REQUEST_TEXTS = 8
MAX_TEXT_CHARACTERS = 24_000


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_revision: str = Field(min_length=1, max_length=128)
    kind: Literal["query", "passage", "health"]
    texts: tuple[
        Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARACTERS)], ...
    ] = Field(default=(), max_length=MAX_REQUEST_TEXTS)
    deadline_ms: int = Field(ge=1, le=30_000)

    @model_validator(mode="after")
    def validate_work(self) -> InferenceRequest:
        expected = 0 if self.kind == "health" else 1
        if len(self.texts) < expected or any(not text.strip() for text in self.texts):
            raise ValueError("Invalid inference input")
        if self.kind in {"health", "query"} and len(self.texts) != expected:
            raise ValueError("Invalid inference input count")
        return self


class InferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_revision: str = Field(min_length=1, max_length=128)
    vectors: list[list[float]] = Field(
        default_factory=list, max_length=MAX_REQUEST_TEXTS
    )
    error: (
        Literal["busy", "deadline", "revision", "invalid", "inference", "stopping"]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_vectors(self) -> InferenceResponse:
        if self.error is not None and self.vectors:
            raise ValueError("Failed inference cannot include vectors")
        for vector in self.vectors:
            if len(vector) != EMBEDDING_DIMENSION or not all(
                math.isfinite(x) for x in vector
            ):
                raise ValueError("Invalid inference vector")
            if not 0.9 <= math.sqrt(sum(x * x for x in vector)) <= 1.1:
                raise ValueError("Inference vector must be normalized")
        return self


def frame(data: bytes) -> bytes:
    if not 0 < len(data) <= MAX_FRAME_BYTES:
        raise ValueError("Inference frame exceeds its byte bound")
    return FRAME_HEADER.pack(len(data)) + data
