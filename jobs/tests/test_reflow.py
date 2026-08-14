from __future__ import annotations

import asyncio
from io import BytesIO
import pymupdf
from unittest.mock import AsyncMock, patch

from PIL import Image

from src.reflow import (
    REFLOW_CHUNK_MAX_CHARS,
    chunk_source_units,
    generate_document_reflow,
    split_source_units,
)
from src.schemas import ReflowChunkLayout, ReflowLayoutItem, ReflowRepairResult


def _pdf_bytes(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 24), line)
    value = document.tobytes()
    document.close()
    return value


def _pdf_with_figure() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Paper")
    page.insert_image(pymupdf.Rect(72, 120, 392, 300), stream=buffer.getvalue())
    page.insert_text((72, 322), "Figure 1: Architecture")
    value = document.tobytes()
    document.close()
    return value


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
                pdf_bytes=_pdf_bytes(
                    "Paper", "A. Author, B. Author", "Source paragraph."
                ),
                page_offset_map={1: [0, len(markdown)]},
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
        "abstract",
        "abstract",
    ]
    assert len(result.profile_revision) == 20
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
                pdf_bytes=_pdf_bytes("Paper", "Source paragraph."),
                page_offset_map={1: [0, 34]},
            )
        )

    assert [block.index for block in result.blocks] == [0, 1]
    assert [block.source_markdown for block in result.blocks] == [
        "# Paper",
        "Source paragraph.",
    ]
    assert result.warnings == ["ai_layout_fallback:0"]


def test_deterministic_repairs_remove_html_without_losing_visible_text() -> None:
    markdown = "# Paper\n\nXiaohang Nie<sup>1,2</sup><!-- parser note -->\n\nBody."
    layout = ReflowChunkLayout(
        items=[
            ReflowLayoutItem(source_index=0, kind="title", heading_level=1),
            ReflowLayoutItem(source_index=1, kind="authors"),
            ReflowLayoutItem(source_index=2, kind="paragraph"),
        ]
    )
    with patch(
        "src.reflow.llm_client.classify_reflow_chunk",
        new=AsyncMock(return_value=(layout, "profile-v2")),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown=markdown,
                pdf_bytes=_pdf_bytes("Paper", "Xiaohang Nie 1,2", "Body."),
                page_offset_map={1: [0, len(markdown)]},
            )
        )

    author = result.blocks[1]
    assert author.source_markdown.endswith("<!-- parser note -->")
    assert author.render_markdown == "Xiaohang Nie$^{1,2}$"
    assert author.presentation_status == "repaired"
    assert "<sup>" not in author.render_markdown


def test_unreliable_visual_repair_degrades_only_the_affected_block() -> None:
    markdown = "# Paper\n\nBroken � equation"
    layout = ReflowChunkLayout(
        items=[
            ReflowLayoutItem(source_index=0, kind="title", heading_level=1),
            ReflowLayoutItem(source_index=1, kind="equation"),
        ]
    )
    with (
        patch(
            "src.reflow.llm_client.classify_reflow_chunk",
            new=AsyncMock(return_value=(layout, "profile-v2")),
        ),
        patch(
            "src.reflow.llm_client.repair_reflow_unit",
            new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
        ),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown=markdown,
                pdf_bytes=_pdf_bytes("Paper", "Broken equation"),
                page_offset_map={1: [0, len(markdown)]},
            )
        )

    assert result.blocks[0].presentation_status == "verbatim"
    assert result.blocks[1].presentation_status == "degraded"
    assert result.warnings == ["visual_repair_failed:1"]


def test_high_confidence_visual_repair_is_accepted_with_pdf_evidence() -> None:
    markdown = "# Paper\n\nBroken � equation"
    layout = ReflowChunkLayout(
        items=[
            ReflowLayoutItem(source_index=0, kind="title", heading_level=1),
            ReflowLayoutItem(source_index=1, kind="equation"),
        ]
    )
    with (
        patch(
            "src.reflow.llm_client.classify_reflow_chunk",
            new=AsyncMock(return_value=(layout, "profile-v2")),
        ),
        patch(
            "src.reflow.llm_client.repair_reflow_unit",
            new=AsyncMock(
                return_value=(
                    ReflowRepairResult(
                        render_markdown="Broken equation", confidence=0.95
                    ),
                    "repair-v1",
                )
            ),
        ),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown=markdown,
                pdf_bytes=_pdf_bytes("Paper", "Broken equation"),
                page_offset_map={1: [0, len(markdown)]},
            )
        )

    assert result.blocks[1].render_markdown == "Broken equation"
    assert result.blocks[1].presentation_status == "repaired"
    assert result.warnings == []


def test_pdf_figure_asset_is_extracted_and_bound_to_its_caption() -> None:
    markdown = "# Paper\n\nFigure 1: Architecture"
    layout = ReflowChunkLayout(
        items=[
            ReflowLayoutItem(source_index=0, kind="title", heading_level=1),
            ReflowLayoutItem(source_index=1, kind="caption"),
        ]
    )
    written: list[tuple[str, str]] = []
    with patch(
        "src.reflow.llm_client.classify_reflow_chunk",
        new=AsyncMock(return_value=(layout, "profile-v2")),
    ):
        result = asyncio.run(
            generate_document_reflow(
                document_id="document-id",
                title="Paper",
                markdown=markdown,
                pdf_bytes=_pdf_with_figure(),
                page_offset_map={1: [0, len(markdown)]},
                write_asset=lambda _data, key, content_type: (
                    written.append((key, content_type)) or key
                ),
            )
        )

    assert len(result.assets) == 1
    assert result.assets[0].kind == "raster"
    assert result.assets[0].page_number == 1
    assert result.blocks[1].asset_id == result.assets[0].id
    assert written == [(result.assets[0].object_key, "image/png")]
