from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src.reflow import (
    REFLOW_CHUNK_MAX_CHARS,
    chunk_source_units,
    generate_document_reflow,
    split_source_units,
)
from src.schemas import ReflowChunkLayout, ReflowLayoutItem


def test_source_splitter_preserves_fenced_blocks_and_bounds_chunks() -> None:
    markdown = (
        "# Paper\n\n"
        "Paragraph.\n\n"
        "```python\nvalue = 1\n\nprint(value)\n```\n\n"
        + ("x" * (REFLOW_CHUNK_MAX_CHARS + 10))
    )

    units = split_source_units(markdown)
    chunks = chunk_source_units(units)

    assert units[0].fallback_kind == "title"
    assert units[2].fallback_kind == "code"
    assert "\n\n" in units[2].markdown
    assert all(len(unit.markdown) <= REFLOW_CHUNK_MAX_CHARS for unit in units)
    assert [unit.index for chunk in chunks for unit in chunk] == list(range(len(units)))


def test_reflow_keeps_source_text_and_accepts_valid_ai_layout() -> None:
    markdown = "# Paper\n\nA. Author, B. Author\n\n## Abstract\n\nSource paragraph."
    layout = ReflowChunkLayout(
        items=[
            ReflowLayoutItem(source_index=0, kind="title", heading_level=1),
            ReflowLayoutItem(source_index=1, kind="authors"),
            ReflowLayoutItem(source_index=2, kind="heading", heading_level=2),
            ReflowLayoutItem(source_index=3, kind="paragraph"),
        ]
    )

    with patch(
        "src.reflow.llm_client.classify_reflow_chunk",
        new=AsyncMock(return_value=(layout, "profile-v1")),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown=markdown,
            )
        )

    assert [block.source_markdown for block in result.blocks] == [
        "# Paper",
        "A. Author, B. Author",
        "## Abstract",
        "Source paragraph.",
    ]
    assert [block.kind for block in result.blocks] == [
        "title",
        "authors",
        "heading",
        "paragraph",
    ]
    assert result.profile_revision == "profile-v1"
    assert result.warnings == []


def test_invalid_ai_indices_fall_back_without_dropping_units() -> None:
    invalid = ReflowChunkLayout(
        items=[ReflowLayoutItem(source_index=1, kind="paragraph")]
    )

    with patch(
        "src.reflow.llm_client.classify_reflow_chunk",
        new=AsyncMock(return_value=(invalid, "profile-v1")),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown="# Paper\n\nSource paragraph.",
            )
        )

    assert [block.index for block in result.blocks] == [0, 1]
    assert [block.source_markdown for block in result.blocks] == [
        "# Paper",
        "Source paragraph.",
    ]
    assert result.warnings == ["ai_chunk_fallback:0"]
