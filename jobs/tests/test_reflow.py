from __future__ import annotations

import hashlib
from io import BytesIO

import pymupdf
from PIL import Image

from src.pdf.models import MinerUArchive
from src.reflow import REFLOW_PIPELINE_REVISION, build_document_reflow


def _png_bytes() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _archive(
    *blocks: dict[str, object], files: dict[str, bytes] | None = None
) -> MinerUArchive:
    return MinerUArchive(content_list=blocks, files=files or {})


def _build(archive: MinerUArchive, *, writer=None, pdf_bytes=b"canonical-pdf"):
    return build_document_reflow(
        document_id="document-id",
        title="Ignored metadata title",
        pdf_bytes=pdf_bytes,
        archive=archive,
        parser_revision="mineru-cloud-v1",
        write_asset=writer,
    )


def test_builds_continuous_academic_ast_from_mineru_reading_order() -> None:
    result = _build(
        _archive(
            {
                "type": "text",
                "text": "Paper title",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [100, 80, 900, 160],
            },
            {
                "type": "text",
                "text": "Ada Lovelace<sup>1</sup><!-- parser note -->",
                "page_idx": 0,
                "bbox": [150, 180, 850, 220],
            },
            {
                "type": "text",
                "text": "Abstract",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [100, 250, 300, 290],
            },
            {
                "type": "text",
                "text": "A faithful reading paragraph.",
                "page_idx": 0,
                "bbox": [100, 310, 900, 430],
            },
        )
    )

    assert [block.kind for block in result.blocks] == [
        "title",
        "authors",
        "heading",
        "abstract",
    ]
    assert result.blocks[1].render_markdown == "Ada Lovelace$^{1}$"
    assert result.blocks[1].group_id == "paper-information"
    assert result.blocks[3].source_spans[0].page_number == 1
    assert result.blocks[3].source_spans[0].source_rect.x == 0.1
    assert result.pipeline_revision == REFLOW_PIPELINE_REVISION
    assert result.parser_revision == "mineru-cloud-v1"
    assert result.source_hash == hashlib.sha256(b"canonical-pdf").hexdigest()


def test_normalizes_adjacent_author_superscripts_without_leaking_tex() -> None:
    result = _build(
        _archive(
            {"type": "text", "text": "Paper", "text_level": 1, "page_idx": 0},
            {
                "type": "text",
                "text": "Ada Lovelace$^{1}$$^{_,3}$$^{_,†}$",
                "page_idx": 0,
            },
            {"type": "text", "text": "Abstract", "text_level": 1, "page_idx": 0},
        )
    )

    assert result.blocks[1].render_markdown == "Ada Lovelace$^{1,3,†}$"


def test_merges_only_clear_split_paragraph_fragments_and_keeps_provenance() -> None:
    result = _build(
        _archive(
            {
                "type": "text",
                "text": "Title",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [0, 0, 1000, 100],
            },
            {
                "type": "text",
                "text": "Abstract",
                "text_level": 2,
                "page_idx": 0,
                "bbox": [0, 100, 1000, 150],
            },
            {
                "type": "text",
                "text": "A sentence split at the page",
                "page_idx": 0,
                "bbox": [0, 200, 1000, 900],
            },
            {
                "type": "text",
                "text": "boundary continues here.",
                "page_idx": 1,
                "bbox": [0, 50, 1000, 200],
            },
            {
                "type": "text",
                "text": "A separate paragraph.",
                "page_idx": 1,
                "bbox": [0, 250, 1000, 350],
            },
        )
    )

    paragraph = result.blocks[2]
    assert paragraph.render_markdown == (
        "A sentence split at the page boundary continues here."
    )
    assert [span.page_number for span in paragraph.source_spans] == [1, 2]
    assert result.blocks[3].render_markdown == "A separate paragraph."


def test_preserves_tables_equations_lists_and_mineru_figure_assets() -> None:
    image = _png_bytes()
    written: list[tuple[str, str]] = []

    def write_asset(_data: bytes, key: str, content_type: str) -> str:
        written.append((key, content_type))
        return key

    result = _build(
        _archive(
            {
                "type": "text",
                "text": "Title",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [0, 0, 1000, 100],
            },
            {
                "type": "text",
                "text": "Introduction",
                "text_level": 2,
                "page_idx": 0,
                "bbox": [0, 100, 1000, 150],
            },
            {
                "type": "list",
                "list_items": ["First", "Second"],
                "page_idx": 0,
                "bbox": [0, 200, 1000, 300],
            },
            {
                "type": "equation",
                "text": "E = mc^2",
                "page_idx": 0,
                "bbox": [0, 320, 1000, 400],
            },
            {
                "type": "table",
                "table_body": "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
                "page_idx": 1,
                "bbox": [0, 100, 1000, 400],
            },
            {
                "type": "image",
                "img_path": "images/figure-1.png",
                "image_caption": ["Figure 1: Architecture"],
                "page_idx": 1,
                "bbox": [100, 450, 900, 900],
            },
            files={"result/images/figure-1.png": image},
        ),
        writer=write_asset,
    )

    assert [block.kind for block in result.blocks[2:]] == [
        "list",
        "equation",
        "table",
        "figure",
        "caption",
    ]
    assert result.blocks[2].render_markdown == "- First\n- Second"
    assert result.blocks[3].render_markdown.startswith("$$")
    assert "| A | B |" in result.blocks[4].render_markdown
    assert result.blocks[5].render_markdown == "Figure 1: Architecture"
    assert result.blocks[5].asset_id == result.assets[0].id
    assert result.blocks[6].render_markdown == "Figure 1: Architecture"
    assert result.blocks[6].group_id == result.blocks[5].group_id
    assert result.assets[0].width == 320
    assert result.assets[0].height == 180
    assert written == [(result.assets[0].object_key, "image/png")]


def test_filters_running_headers_but_keeps_footnotes_and_references() -> None:
    result = _build(
        _archive(
            {"type": "header", "text": "Journal name", "page_idx": 0},
            {"type": "aside_text", "text": "arXiv sidebar", "page_idx": 0},
            {"type": "text", "text": "Title", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "Body", "text_level": 2, "page_idx": 0},
            {"type": "page_footnote", "text": "1 Footnote", "page_idx": 0},
            {"type": "text", "text": "References", "text_level": 2, "page_idx": 1},
            {"type": "text", "text": "[1] Source", "page_idx": 1},
            {"type": "page_number", "text": "2", "page_idx": 1},
        )
    )

    assert [block.kind for block in result.blocks] == [
        "title",
        "heading",
        "footnote",
        "heading",
        "references",
    ]
    assert all("Journal name" not in block.render_markdown for block in result.blocks)
    assert all("arXiv sidebar" not in block.render_markdown for block in result.blocks)
    assert result.blocks[0].render_markdown.startswith("# ")
    assert result.blocks[1].render_markdown.startswith("## ")


def test_missing_visual_asset_degrades_only_the_figure() -> None:
    result = _build(
        _archive(
            {"type": "text", "text": "Title", "text_level": 1, "page_idx": 0},
            {
                "type": "image",
                "img_path": "images/missing.png",
                "image_caption": "Figure 1",
                "page_idx": 2,
            },
        )
    )

    assert result.blocks[0].presentation_status == "verbatim"
    assert result.blocks[1].presentation_status == "degraded"
    assert result.warnings == ["reflow_asset_missing:3"]


def test_combines_adjacent_visual_tiles_using_the_canonical_pdf_region() -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(pymupdf.Rect(60, 80, 540, 360), color=(0, 0, 0))
    page.insert_text((80, 120), "Composite figure evidence")
    pdf_bytes = document.tobytes()
    document.close()
    written: list[tuple[bytes, str, str]] = []

    def write_asset(data: bytes, key: str, content_type: str) -> str:
        written.append((data, key, content_type))
        return key

    result = _build(
        _archive(
            {"type": "text", "text": "Title", "text_level": 1, "page_idx": 0},
            {
                "type": "image",
                "img_path": "images/panel-a.png",
                "page_idx": 0,
                "bbox": [100, 100, 500, 450],
            },
            {
                "type": "image",
                "img_path": "images/panel-b.png",
                "image_caption": ["Figure 1: Combined panels"],
                "page_idx": 0,
                "bbox": [500, 100, 900, 450],
            },
        ),
        writer=write_asset,
        pdf_bytes=pdf_bytes,
    )

    assert [block.kind for block in result.blocks] == [
        "title",
        "figure",
        "caption",
    ]
    assert len(result.assets) == 1
    assert len(result.blocks[1].source_spans) == 2
    assert result.blocks[2].render_markdown == "Figure 1: Combined panels"
    assert written[0][0].startswith(b"\x89PNG")
    assert written[0][2] == "image/png"


def test_drops_source_table_of_contents_and_derives_section_depth() -> None:
    result = _build(
        _archive(
            {"type": "text", "text": "Paper", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "Contents", "text_level": 1, "page_idx": 1},
            {"type": "text", "text": "1 Introduction ........ 3", "page_idx": 1},
            {
                "type": "text",
                "text": "1 Introduction",
                "text_level": 1,
                "page_idx": 2,
            },
            {
                "type": "text",
                "text": "1.1 Motivation",
                "text_level": 1,
                "page_idx": 2,
            },
            {"type": "text", "text": r"\- First point", "page_idx": 2},
        )
    )

    assert [block.kind for block in result.blocks] == [
        "title",
        "heading",
        "heading",
        "list",
    ]
    assert result.blocks[1].render_markdown == "## 1 Introduction"
    assert result.blocks[2].render_markdown == "### 1.1 Motivation"
    assert result.blocks[3].render_markdown == "- First point"
