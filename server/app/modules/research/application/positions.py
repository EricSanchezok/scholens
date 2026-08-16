"""Canonical, transport-safe anchors for research content."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PdfTextRect(BaseModel):
    """A PDF text rectangle normalized to the page's 0–1 coordinate space."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(
        ge=0,
        le=1,
        description="Normalized left coordinate from 0 at the page edge to 1.",
    )
    y: float = Field(
        ge=0,
        le=1,
        description="Normalized top coordinate from 0 at the page edge to 1.",
    )
    width: float = Field(
        gt=0,
        le=1,
        description="Normalized positive rectangle width within the page.",
    )
    height: float = Field(
        gt=0,
        le=1,
        description="Normalized positive rectangle height within the page.",
    )

    @model_validator(mode="after")
    def stay_inside_page(self) -> PdfTextRect:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("PDF text rectangle must stay within the page")
        return self


class PdfTextPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["pdf_text"] = Field(
        default="pdf_text",
        description="Anchor the quote to visible PDF text rectangles.",
    )
    page_number: int = Field(
        ge=1,
        description="One-based PDF page containing every supplied rectangle.",
    )
    rects: list[PdfTextRect] = Field(
        min_length=1,
        max_length=200,
        description="Ordered normalized rectangles covering the exact selected quote.",
    )


class ParsedTextPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["parsed_text"] = Field(
        default="parsed_text",
        description="Anchor the quote to offsets in canonical parsed paper text.",
    )
    start_offset: int = Field(
        ge=0,
        description="Inclusive zero-based character offset in canonical parsed text.",
    )
    end_offset: int = Field(
        gt=0,
        description="Exclusive zero-based character offset after the selected quote.",
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        description="Optional one-based source page projection for the parsed-text span.",
    )

    @model_validator(mode="after")
    def validate_span(self) -> ParsedTextPosition:
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must follow start_offset")
        return self


ResearchPosition = Annotated[
    PdfTextPosition | ParsedTextPosition,
    Field(discriminator="kind"),
]


def position_columns(
    position: ResearchPosition | None,
) -> tuple[int | None, int | None, int | None]:
    """Project a typed anchor into indexed persistence columns."""

    if isinstance(position, PdfTextPosition):
        return position.page_number, None, None
    if isinstance(position, ParsedTextPosition):
        return position.page_number, position.start_offset, position.end_offset
    return None, None, None


__all__ = [
    "ParsedTextPosition",
    "PdfTextPosition",
    "PdfTextRect",
    "ResearchPosition",
    "position_columns",
]
