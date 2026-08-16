from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DoiPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["doi"] = Field(
        default="doi",
        description="Import one already-known paper by DOI.",
    )
    doi: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "A known DOI for the paper to import. Supply the canonical identifier, "
            "not a title, keywords, or a request to discover papers."
        ),
    )


class ArxivPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["arxiv"] = Field(
        default="arxiv",
        description="Import one already-known paper by arXiv identifier.",
    )
    arxiv_id: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "A known arXiv identifier such as '1706.03762'. Do not put a search "
            "query or paper title here."
        ),
    )


class UrlPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"] = Field(
        default="url",
        description="Import one already-known reachable HTTP(S) paper source.",
    )
    url: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "The already-known HTTP(S) URL of a PDF or supported paper source. "
            "This imports the URL; it does not search the internet."
        ),
    )


class UploadPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["upload"] = Field(
        default="upload",
        description="Ingest bytes already transferred through a prepared upload session.",
    )
    upload_id: UUID = Field(
        description=(
            "The upload session UUID returned by prepare_paper_upload after the PDF "
            "bytes were uploaded with the supplied URL and headers."
        )
    )


PaperSource = Annotated[
    DoiPaperSource | ArxivPaperSource | UrlPaperSource | UploadPaperSource,
    Field(discriminator="kind"),
]


class PaperIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: PaperSource = Field(
        description=(
            "One already-known paper source. Use upload only after preparing and "
            "transferring a local PDF; Scholens does not discover papers from queries."
        )
    )
    project_id: UUID | None = Field(
        default=None,
        description=(
            "Optional immutable Scholens Project UUID that should receive the paper "
            "when ingestion succeeds. For an upload source, this must exactly match the "
            "Project bound by the upload preparation. Read it from the repository binding "
            "or a Project tool."
        ),
    )
