"""Typed user context attached to one conversation turn."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from app.modules.research.application.positions import PdfTextPosition
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaperSelectionTurnContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["paper_selection"] = "paper_selection"
    document_id: uuid.UUID
    page_number: int = Field(ge=1)
    selected_text: str = Field(min_length=1, max_length=20_000)
    anchor: PdfTextPosition

    @model_validator(mode="after")
    def anchor_matches_page(self) -> PaperSelectionTurnContext:
        if self.anchor.page_number != self.page_number:
            raise ValueError("paper selection page_number must match its anchor")
        return self


class AnnotationThreadTurnContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["annotation_thread"] = "annotation_thread"
    thread_id: uuid.UUID


TurnContext = Annotated[
    PaperSelectionTurnContext | AnnotationThreadTurnContext,
    Field(discriminator="kind"),
]


__all__ = [
    "AnnotationThreadTurnContext",
    "PaperSelectionTurnContext",
    "TurnContext",
]
