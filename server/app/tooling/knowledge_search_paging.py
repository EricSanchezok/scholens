"""Composite continuation primitives for bounded workspace knowledge search."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.papers.application.contracts.search import PaperSearchSort
from app.shared.application import SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.tooling import workspace_contracts as wc

KnowledgeProducer = Literal[
    "paper",
    "paper_passage",
    "annotation_thread",
    "annotation_comment",
    "research_output",
]

_PRODUCER_PRIORITY: dict[KnowledgeProducer, int] = {
    "paper_passage": 0,
    "annotation_thread": 1,
    "annotation_comment": 2,
    "paper": 3,
    "research_output": 4,
}


@dataclass(frozen=True, slots=True)
class PaperKnowledgeSourceKey:
    actor_id: int
    request_json: str
    offset: int


@dataclass(frozen=True, slots=True)
class AnnotationKnowledgeSourceKey:
    actor_id: int
    query: str
    scope_kind: str
    document_id: UUID | None
    project_id: UUID | None
    after_created_at: datetime | None
    after_item_id: UUID | None
    limit: int


class KnowledgeProducerPosition(BaseModel):
    """Next unread location in one independently bounded producer stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: int = Field(default=0, ge=0, le=(1 << 63) - 1)
    child_index: int = Field(default=0, ge=0, le=3)
    anchor_key: str | None = Field(default=None, max_length=128)
    anchor_id: UUID | None = None
    exhausted: bool = False


class KnowledgeSearchCursorState(BaseModel):
    """All producer continuations carried by one signed public cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper: KnowledgeProducerPosition = Field(default_factory=KnowledgeProducerPosition)
    paper_passage: KnowledgeProducerPosition = Field(
        default_factory=KnowledgeProducerPosition
    )
    annotation_thread: KnowledgeProducerPosition = Field(
        default_factory=KnowledgeProducerPosition
    )
    annotation_comment: KnowledgeProducerPosition = Field(
        default_factory=KnowledgeProducerPosition
    )
    research_output: KnowledgeProducerPosition = Field(
        default_factory=KnowledgeProducerPosition
    )

    def position(self, producer: KnowledgeProducer) -> KnowledgeProducerPosition:
        if producer == "paper":
            return self.paper
        if producer == "paper_passage":
            return self.paper_passage
        if producer == "annotation_thread":
            return self.annotation_thread
        if producer == "annotation_comment":
            return self.annotation_comment
        return self.research_output

    def advanced(
        self,
        producer: KnowledgeProducer,
        position: KnowledgeProducerPosition,
    ) -> KnowledgeSearchCursorState:
        return self.model_copy(update={producer: position})


@dataclass(frozen=True, slots=True)
class RankedKnowledgeCandidate:
    producer: KnowledgeProducer
    rank: int
    child_rank: int
    sort_time: datetime
    item: wc.KnowledgeSearchResult
    next_position: KnowledgeProducerPosition

    def sort_key(self, sort: PaperSearchSort) -> tuple[object, ...]:
        """Return a total order whose restriction to each producer is monotonic."""

        if sort is PaperSearchSort.RECENT:
            return (
                -self.sort_time.timestamp(),
                _PRODUCER_PRIORITY[self.producer],
                self.rank,
                self.child_rank,
                str(self.item.entity_id),
            )
        return (
            self.rank,
            self.child_rank,
            _PRODUCER_PRIORITY[self.producer],
            -self.sort_time.timestamp(),
            str(self.item.entity_id),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeProducerWindow:
    producer: KnowledgeProducer
    candidates: tuple[RankedKnowledgeCandidate, ...]
    scan_position: KnowledgeProducerPosition
    source_has_more: bool


def knowledge_rank_score(*, rank: int, child_rank: int) -> float:
    """Normalize independent producer ranks without pretending scores are comparable."""

    return 1.0 + (1.0 / (60.0 + rank * 4 + child_rank + 1))


def knowledge_cursor_fingerprint(
    *,
    actor_id: int,
    request: wc.SearchKnowledgeInput,
) -> str:
    """Bind a continuation to actor, scope, query, filters, sort, kinds, and limit."""

    return json.dumps(
        {
            "actor_id": actor_id,
            "request": request.model_dump(mode="json", exclude={"cursor"}),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_knowledge_cursor(
    *,
    codec: SignedCursorCodec,
    cursor: str | None,
    fingerprint: str,
) -> KnowledgeSearchCursorState:
    if cursor is None:
        return KnowledgeSearchCursorState()
    (encoded_state,) = codec.decode_keyset(
        cursor=cursor,
        fingerprint=fingerprint,
        arity=1,
    )
    try:
        return KnowledgeSearchCursorState.model_validate_json(encoded_state)
    except (ValidationError, ValueError) as error:
        raise AppError(
            code="knowledge_search_cursor_invalid",
            message="The knowledge-search cursor is invalid or expired",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from error


def encode_knowledge_cursor(
    *,
    codec: SignedCursorCodec,
    state: KnowledgeSearchCursorState,
    fingerprint: str,
) -> str:
    return codec.encode_keyset(
        fingerprint=fingerprint,
        values=(state.model_dump_json(exclude_defaults=True),),
    )


__all__ = [
    "AnnotationKnowledgeSourceKey",
    "KnowledgeProducer",
    "KnowledgeProducerPosition",
    "KnowledgeProducerWindow",
    "KnowledgeSearchCursorState",
    "PaperKnowledgeSourceKey",
    "RankedKnowledgeCandidate",
    "decode_knowledge_cursor",
    "encode_knowledge_cursor",
    "knowledge_cursor_fingerprint",
    "knowledge_rank_score",
]
