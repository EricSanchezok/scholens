"""Lossless AI-assisted layout classification for canonical paper Markdown."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from scholens_ai import AIProfileName, resolve_profile
from src.llm_client import llm_client
from src.schemas import (
    DocumentReflowBlock,
    DocumentReflowResult,
    ReflowBlockKind,
    ReflowChunkLayout,
    ReflowLayoutItem,
)

REFLOW_PROMPT_REVISION = "reflow-layout-v1"
REFLOW_CHUNK_MAX_CHARS = 20_000
_HEADING = re.compile(r"^(#{1,6})\s+")
_LIST = re.compile(r"^(?:[-+*]|\d+[.)])\s+")
_FIGURE = re.compile(r"^(?:!\[|(?:figure|fig\.)\s*\d+)", re.IGNORECASE)
_REFERENCE_HEADING = re.compile(
    r"^#{1,6}\s+(?:references|bibliography)\s*$", re.IGNORECASE
)


def reflow_source_hash(markdown: str) -> str:
    """Hash ordered tokens while allowing layout-only whitespace changes."""

    return hashlib.sha256(" ".join(markdown.split()).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceUnit:
    index: int
    markdown: str
    fallback_kind: ReflowBlockKind
    fallback_heading_level: int | None = None
    source_start: int = 0


def _classify(markdown: str, *, index: int) -> tuple[ReflowBlockKind, int | None]:
    stripped = markdown.lstrip()
    heading = _HEADING.match(stripped)
    if heading:
        if _REFERENCE_HEADING.match(stripped):
            return "references", len(heading.group(1))
        return ("title" if index == 0 else "heading"), len(heading.group(1))
    if stripped.startswith("```"):
        return "code", None
    if stripped.startswith(("$$", "\\[", "\\begin{equation}")):
        return "equation", None
    if stripped.startswith(">"):
        return "quote", None
    if _LIST.match(stripped):
        return "list", None
    if stripped.startswith("|") and "|" in stripped[1:]:
        return "table", None
    if _FIGURE.match(stripped):
        return "figure", None
    if index == 1 and len(stripped) < 1_000 and "," in stripped:
        return "authors", None
    return "paragraph", None


def split_source_units(markdown: str) -> list[SourceUnit]:
    """Split at blank lines while keeping fenced code and display math intact."""

    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("reflow_source_empty")
    units: list[str] = []
    current: list[str] = []
    in_fence = False
    in_math = False
    for line in normalized.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if stripped == "$$" and not in_fence:
            in_math = not in_math
        if not stripped and not in_fence and not in_math:
            if current:
                units.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        units.append("\n".join(current).strip())

    result: list[SourceUnit] = []
    cursor = 0
    for markdown_unit in units:
        unit_start = normalized.find(markdown_unit, cursor)
        if unit_start < 0:
            raise RuntimeError("reflow_source_unit_offset_missing")
        # A pathological parser paragraph must not make one provider request huge.
        pieces = [
            markdown_unit[offset : offset + REFLOW_CHUNK_MAX_CHARS]
            for offset in range(0, len(markdown_unit), REFLOW_CHUNK_MAX_CHARS)
        ]
        piece_offset = 0
        for piece in pieces:
            index = len(result)
            kind, level = _classify(piece, index=index)
            result.append(
                SourceUnit(
                    index=index,
                    markdown=piece,
                    fallback_kind=kind,
                    fallback_heading_level=level,
                    source_start=unit_start + piece_offset,
                )
            )
            piece_offset += len(piece)
        cursor = unit_start + len(markdown_unit)
    return result


def chunk_source_units(units: list[SourceUnit]) -> list[list[SourceUnit]]:
    chunks: list[list[SourceUnit]] = []
    current: list[SourceUnit] = []
    current_chars = 0
    for unit in units:
        request_chars = len(unit.markdown) + 32
        if current and current_chars + request_chars > REFLOW_CHUNK_MAX_CHARS:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += request_chars
    if current:
        chunks.append(current)
    return chunks


def _prompt(title: str, chunk: list[SourceUnit]) -> str:
    source = "\n\n".join(
        f'<unit source_index="{unit.index}">\n{unit.markdown}\n</unit>'
        for unit in chunk
    )
    return (
        "Identify the reading-layout role of every unit from an academic paper. "
        "Allowed kinds: title, authors, heading, paragraph, list, quote, equation, "
        "table, figure, code, references. Set heading_level only for title, heading, "
        "or references. Keep all source_index values exactly once and in ascending "
        f"order. Paper title: {title}\n\n{source}"
    )


def _validated_layout(
    layout: ReflowChunkLayout,
    chunk: list[SourceUnit],
) -> list[ReflowLayoutItem]:
    expected = [unit.index for unit in chunk]
    actual = [item.source_index for item in layout.items]
    if actual != expected:
        raise ValueError("reflow_layout_indices_invalid")
    return layout.items


def _fallback_layout(chunk: list[SourceUnit]) -> list[ReflowLayoutItem]:
    return [
        ReflowLayoutItem(
            source_index=unit.index,
            kind=unit.fallback_kind,
            heading_level=unit.fallback_heading_level,
        )
        for unit in chunk
    ]


async def generate_document_reflow(
    *,
    document_id: str,
    title: str,
    markdown: str,
    page_offset_map: dict[int, list[int]] | None = None,
) -> DocumentReflowResult:
    units = split_source_units(markdown)
    layouts: dict[int, ReflowLayoutItem] = {}
    warnings: list[str] = []
    profile_revision = resolve_profile(AIProfileName.REFLOW).revision
    for chunk_index, chunk in enumerate(chunk_source_units(units)):
        try:
            result, profile_revision = await llm_client.classify_reflow_chunk(
                prompt=_prompt(title, chunk),
                chunk_index=chunk_index,
            )
            items = _validated_layout(result, chunk)
        except Exception:
            items = _fallback_layout(chunk)
            warnings.append(f"ai_chunk_fallback:{chunk_index}")
        layouts.update({item.source_index: item for item in items})

    page_bounds = page_offset_map or {}

    def page_for(unit: SourceUnit) -> int | None:
        return next(
            (
                page
                for page, bounds in sorted(page_bounds.items())
                if len(bounds) == 2 and bounds[0] <= unit.source_start < bounds[1]
            ),
            None,
        )

    blocks = [
        DocumentReflowBlock(
            id=hashlib.sha256(
                f"{document_id}:{unit.index}:{unit.markdown}".encode()
            ).hexdigest()[:32],
            index=unit.index,
            kind=layouts[unit.index].kind,
            source_markdown=unit.markdown,
            heading_level=layouts[unit.index].heading_level,
            page_number=page_for(unit),
        )
        for unit in units
    ]
    return DocumentReflowResult(
        document_id=document_id,
        source_hash=reflow_source_hash(markdown),
        prompt_revision=REFLOW_PROMPT_REVISION,
        profile_revision=profile_revision,
        blocks=blocks,
        warnings=warnings,
    )
