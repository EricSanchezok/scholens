"""Algorithm-neutral contracts for searching canonical papers and their text."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.papers.application.contracts.documents import (
    LibraryPaperTagResponse,
    PublicUtcDateTime,
)
from app.shared.domain.enums import PaperStatus


class LibraryPaperCollection(BaseModel):
    """All documents readable through personal or Project-based access."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["library"] = "library"


class PersonalLibraryPaperCollection(BaseModel):
    """Only documents explicitly saved in the actor's personal Library."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["personal_library"] = "personal_library"


class SelectedPaperCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["selection"] = "selection"
    project_ids: list[UUID] = Field(default_factory=list, max_length=20)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("project_ids", "document_ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return sorted({str(UUID(str(item))) for item in value})

    @model_validator(mode="after")
    def require_nonempty(self) -> SelectedPaperCollection:
        if not self.project_ids and not self.document_ids:
            raise ValueError("A selected paper collection cannot be empty")
        return self


PaperCollection = Annotated[
    LibraryPaperCollection | PersonalLibraryPaperCollection | SelectedPaperCollection,
    Field(discriminator="kind"),
]


class PaperSearchSort(StrEnum):
    RELEVANCE = "relevance"
    RECENT = "recent"


class PaperSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published_from: datetime | None = Field(
        default=None,
        description="Optional inclusive earliest publication timestamp.",
    )
    published_to: datetime | None = Field(
        default=None,
        description="Optional inclusive latest publication timestamp.",
    )
    personal_statuses: list[PaperStatus] = Field(
        default_factory=list,
        max_length=3,
        description="Optional personal Library statuses matched with OR semantics.",
    )
    personal_tag_ids: list[UUID] = Field(
        default_factory=list,
        max_length=120,
        description="Optional personal Library tag identifiers matched with OR semantics.",
    )

    @field_validator("personal_statuses", "personal_tag_ids")
    @classmethod
    def reject_duplicates(
        cls,
        value: list[PaperStatus] | list[UUID],
    ) -> list[PaperStatus] | list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("personal metadata filters must be unique")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> PaperSearchFilters:
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            raise ValueError("published_from must not be after published_to")
        return self


class PaperSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1_000)
    collection: PaperCollection = Field(default_factory=LibraryPaperCollection)
    filters: PaperSearchFilters = Field(default_factory=PaperSearchFilters)
    sort: PaperSearchSort = PaperSearchSort.RELEVANCE
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1_024)


class PaperSearchQuery(BaseModel):
    """Internal request supplied to a replaceable search adapter."""

    query: str
    collection: PaperCollection
    filters: PaperSearchFilters
    sort: PaperSearchSort
    limit: int
    offset: int = Field(ge=0)


class PaperSearchSnippet(BaseModel):
    text: str
    start_line: int | None = None
    end_line: int | None = None


class PaperSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    title: str | None
    authors: list[str] | None
    abstract: str | None
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    doi: str | None = None
    journal: str | None = None
    status: str
    publish_date: PublicUtcDateTime | None
    created_at: datetime
    last_accessed_at: datetime
    preview_url: str | None = None
    personal_status: PaperStatus | None = None
    personal_tags: list[LibraryPaperTagResponse] = Field(default_factory=list)
    personal_last_accessed_at: datetime | None = None
    matched_fields: list[str] = Field(default_factory=list)
    retrieval_modes: list[Literal["exact", "full_text", "fuzzy", "semantic"]] = Field(
        default_factory=list
    )
    snippets: list[PaperSearchSnippet] = Field(default_factory=list)


class PaperSearchResponse(BaseModel):
    items: list[PaperSearchResult]
    total: int
    next_cursor: str | None = None
    search_mode: Literal["hybrid", "lexical"] = "lexical"
    semantic_index_coverage: float = Field(default=0, ge=0, le=1)


class PaperSearchStats(BaseModel):
    total_papers: int
    searchable_items: int
    semantic_items: int = 0
    semantic_index_coverage: float = Field(default=0, ge=0, le=1)
