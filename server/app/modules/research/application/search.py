"""Independent search capability for annotation threads and comments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.shared.application import Actor, SignedCursorCodec
from app.modules.research.application.positions import ResearchPosition
from pydantic import BaseModel, ConfigDict, Field, model_validator

RESEARCH_SEARCH_REVISION = "research-search:1"


class ResearchSearchScopeKind(StrEnum):
    ALL_ACCESSIBLE = "all_accessible"
    PERSONAL_LIBRARY = "personal_library"
    PROJECT = "project"
    PAPER = "paper"


@dataclass(frozen=True, slots=True)
class ResearchSearchScope:
    kind: ResearchSearchScopeKind
    document_id: UUID | None = None
    project_id: UUID | None = None

    def __post_init__(self) -> None:
        valid = (
            (
                self.kind
                in {
                    ResearchSearchScopeKind.ALL_ACCESSIBLE,
                    ResearchSearchScopeKind.PERSONAL_LIBRARY,
                }
                and self.document_id is None
                and self.project_id is None
            )
            or (
                self.kind is ResearchSearchScopeKind.PROJECT
                and self.document_id is None
                and self.project_id is not None
            )
            or (
                self.kind is ResearchSearchScopeKind.PAPER
                and self.document_id is not None
            )
        )
        if not valid:
            raise ValueError("research-search scope identifiers are inconsistent")

    @classmethod
    def all_accessible(cls) -> ResearchSearchScope:
        return cls(kind=ResearchSearchScopeKind.ALL_ACCESSIBLE)

    @classmethod
    def personal_library(cls) -> ResearchSearchScope:
        return cls(kind=ResearchSearchScopeKind.PERSONAL_LIBRARY)

    @classmethod
    def project(cls, project_id: UUID) -> ResearchSearchScope:
        return cls(kind=ResearchSearchScopeKind.PROJECT, project_id=project_id)

    @classmethod
    def paper(
        cls,
        document_id: UUID,
        *,
        project_id: UUID | None = None,
    ) -> ResearchSearchScope:
        return cls(
            kind=ResearchSearchScopeKind.PAPER,
            document_id=document_id,
            project_id=project_id,
        )


class ResearchSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1_000)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1_024)


class ResearchSearchPosition(BaseModel):
    """Stable source-order anchor for bounded annotation candidate windows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime
    item_id: UUID


class ResearchSearchQuery(BaseModel):
    query: str
    limit: int
    offset: int = Field(ge=0)
    include_total: bool = True
    scope: ResearchSearchScope = Field(
        default_factory=ResearchSearchScope.all_accessible
    )
    after: ResearchSearchPosition | None = None

    @model_validator(mode="after")
    def require_one_continuation_style(self) -> ResearchSearchQuery:
        if self.after is not None and self.offset != 0:
            raise ValueError("research search cannot combine offset and keyset")
        return self


class ResearchSearchComment(BaseModel):
    id: UUID
    content: str
    role: str
    created_at: datetime


class ResearchSearchResult(BaseModel):
    id: UUID
    document_id: UUID
    project_id: UUID | None
    document_title: str | None
    quote_text: str
    position: ResearchPosition | None
    role: str
    created_at: datetime
    matching_comments: list[ResearchSearchComment]


class ResearchSearchResponse(BaseModel):
    items: list[ResearchSearchResult]
    total: int
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchSearchCandidatePage:
    items: tuple[ResearchSearchResult, ...]
    has_more: bool


class ResearchSearchPort(Protocol):
    def search(
        self,
        *,
        actor: Actor,
        request: ResearchSearchQuery,
    ) -> ResearchSearchResponse: ...


class SearchResearch:
    def __init__(self, search: ResearchSearchPort, cursors: SignedCursorCodec) -> None:
        self._search = search
        self._cursors = cursors

    def __call__(
        self,
        *,
        actor: Actor,
        request: ResearchSearchRequest,
    ) -> ResearchSearchResponse:
        normalized = request.model_copy(update={"query": request.query.strip()})
        fingerprint = json.dumps(
            normalized.model_dump(mode="json", exclude={"cursor"}),
            separators=(",", ":"),
            sort_keys=True,
        )
        offset = (
            self._cursors.decode(
                cursor=request.cursor,
                fingerprint=fingerprint,
            )
            if request.cursor
            else 0
        )
        response = self._search.search(
            actor=actor,
            request=ResearchSearchQuery(
                query=normalized.query,
                limit=normalized.limit,
                offset=offset,
                include_total=True,
                scope=ResearchSearchScope.all_accessible(),
            ),
        )
        consumed = offset + len(response.items)
        next_cursor = (
            self._cursors.encode(fingerprint=fingerprint, offset=consumed)
            if consumed < response.total
            else None
        )
        return response.model_copy(update={"next_cursor": next_cursor})

    def candidate_page(
        self,
        *,
        actor: Actor,
        query: str,
        limit: int,
        scope: ResearchSearchScope,
        after: ResearchSearchPosition | None,
    ) -> ResearchSearchCandidatePage:
        """Return one count-free keyset window for a composite knowledge search."""

        normalized = ResearchSearchRequest(query=query, limit=limit)
        response = self._search.search(
            actor=actor,
            request=ResearchSearchQuery(
                query=normalized.query.strip(),
                limit=normalized.limit + 1,
                offset=0,
                include_total=False,
                scope=scope,
                after=after,
            ),
        )
        has_more = len(response.items) > normalized.limit
        return ResearchSearchCandidatePage(
            items=tuple(response.items[: normalized.limit]),
            has_more=has_more,
        )


def build_research_search_cursor(secret: str) -> SignedCursorCodec:
    return SignedCursorCodec(
        secret,
        revision=RESEARCH_SEARCH_REVISION,
        error_code="research_search_cursor_expired",
    )
