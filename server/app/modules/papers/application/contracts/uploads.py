from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DoiPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["doi"]
    value: str = Field(min_length=1, max_length=500)


class ArxivPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["arxiv"]
    value: str = Field(min_length=1, max_length=500)


class UrlPaperSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"]
    value: str = Field(min_length=1, max_length=2048)


PaperSource = Annotated[
    DoiPaperSource | ArxivPaperSource | UrlPaperSource,
    Field(discriminator="kind"),
]


class UploadFromSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: PaperSource
    project_id: UUID | None = None
