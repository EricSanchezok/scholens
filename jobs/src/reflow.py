"""Build a continuous academic reading AST from MinerU's structured output."""

from __future__ import annotations

import hashlib
import html
import mimetypes
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

import pymupdf

from src.pdf.mineru import MinerUClient
from src.pdf.models import MinerUArchive
from src.schemas import (
    DocumentReflowAsset,
    DocumentReflowBlock,
    DocumentReflowResult,
    ReflowAssetKind,
    ReflowBlockKind,
    ReflowPresentationStatus,
    ReflowSourceRect,
    ReflowSourceSpan,
)

REFLOW_PIPELINE_REVISION = "mineru-continuous-ast-v1"
_AUXILIARY_TYPES = {"header", "footer", "page_number", "aside"}
_TERMINAL = re.compile(r"[.!?。！？:：;；)”’'\]]$")
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_SUP = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.IGNORECASE | re.DOTALL)
_SUB = re.compile(r"<sub\b[^>]*>(.*?)</sub>", re.IGNORECASE | re.DOTALL)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BROKEN_TEX_SUPERSCRIPT = re.compile(
    r"(?<!\$)(?:\$\$)?\^\{?([^{}$]{1,12})\}?(?:\$\$)?", re.IGNORECASE
)

AssetWriter = Callable[[bytes, str, str], str]


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: ReflowBlockKind
    markdown: str
    heading_level: int | None
    spans: tuple[ReflowSourceSpan, ...]
    presentation_status: ReflowPresentationStatus = "verbatim"
    group_id: str | None = None
    asset_id: str | None = None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _as_text(
                    item.get("text") or item.get("content") or item.get("body")
                )
            else:
                text = str(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    return ""


def _plain_text(value: str) -> str:
    value = _HTML_COMMENT.sub("", value)
    value = _BR.sub(" ", value)
    value = _TAG.sub("", value)
    return " ".join(html.unescape(value).replace("\x00", "").split())


def _safe_markdown(value: str, *, prose: bool = True) -> tuple[str, bool]:
    """Normalize provider markup without ever enabling arbitrary HTML."""

    original = value
    value = html.unescape(value.replace("\x00", ""))
    value = _HTML_COMMENT.sub("", value)
    value = _SUP.sub(lambda match: f"$^{{{_plain_text(match.group(1))}}}$", value)
    value = _SUB.sub(lambda match: f"$_{{{_plain_text(match.group(1))}}}$", value)
    value = _BR.sub("  \n", value)
    value = _TAG.sub("", value)
    value = _BROKEN_TEX_SUPERSCRIPT.sub(
        lambda match: f"$^{{{match.group(1).strip()}}}$", value
    )
    if prose:
        value = re.sub(r"(?<=\w)-\s*\n\s*(?=[a-z])", "", value)
        value = re.sub(r"(?<!\n)\n(?!\n)", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    degraded = "�" in value
    value = value.replace("�", "")
    return value, degraded or value != original.strip()


def _bbox(block: dict[str, Any]) -> ReflowSourceRect:
    raw = block.get("bbox")
    if not isinstance(raw, list) or len(raw) != 4:
        return ReflowSourceRect(x=0, y=0, width=1, height=1)
    try:
        x0, y0, x1, y1 = (float(item) for item in raw)
    except (TypeError, ValueError):
        return ReflowSourceRect(x=0, y=0, width=1, height=1)
    scale = 1000.0 if max(abs(x0), abs(y0), abs(x1), abs(y1)) > 1 else 1.0
    x0, y0, x1, y1 = (item / scale for item in (x0, y0, x1, y1))
    x0 = max(0.0, min(1.0, x0))
    y0 = max(0.0, min(1.0, y0))
    x1 = max(x0 + 0.0001, min(1.0, x1))
    y1 = max(y0 + 0.0001, min(1.0, y1))
    return ReflowSourceRect(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def _page_number(block: dict[str, Any]) -> int:
    try:
        return max(1, int(block.get("page_idx", 0) or 0) + 1)
    except (TypeError, ValueError):
        return 1


def _span(block: dict[str, Any], text: str) -> ReflowSourceSpan:
    return ReflowSourceSpan(
        page_number=_page_number(block),
        source_rect=_bbox(block),
        source_text=text or "[visual content]",
    )


def _table_markdown(value: str) -> tuple[str, bool]:
    if "<table" not in value.lower():
        safe, changed = _safe_markdown(value, prose=False)
        return safe, changed
    parser = _TableParser()
    try:
        parser.feed(value)
    except Exception:
        return _plain_text(value), True
    if not parser.rows:
        return _plain_text(value), True
    width = max(len(row) for row in parser.rows)
    rows = [row + [""] * (width - len(row)) for row in parser.rows]

    def escape(cell: str) -> str:
        return cell.replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(escape(cell) for cell in rows[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend(
        "| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows[1:]
    )
    return "\n".join(lines), True


def _resolve_archive_file(
    archive: MinerUArchive, path_value: object
) -> tuple[str, bytes] | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    wanted = PurePosixPath(path_value).as_posix().lstrip("./")
    direct = archive.files.get(wanted)
    if direct is not None:
        return wanted, direct
    matches = [
        (name, data)
        for name, data in archive.files.items()
        if name.endswith(f"/{wanted}")
        or PurePosixPath(name).name == PurePosixPath(wanted).name
    ]
    return matches[0] if len(matches) == 1 else None


def _asset_dimensions(data: bytes, suffix: str) -> tuple[int, int]:
    try:
        if suffix == ".svg":
            document = pymupdf.open(stream=data, filetype="svg")
            try:
                page = document[0]
                return max(1, round(page.rect.width)), max(1, round(page.rect.height))
            finally:
                document.close()
        pixmap = pymupdf.Pixmap(data)
        return max(1, pixmap.width), max(1, pixmap.height)
    except Exception:
        return 1, 1


def _asset_from_block(
    *,
    archive: MinerUArchive,
    block: dict[str, Any],
    document_id: str,
    write_asset: AssetWriter | None,
) -> DocumentReflowAsset | None:
    resolved = _resolve_archive_file(
        archive,
        block.get("img_path") or block.get("image_path") or block.get("chart_path"),
    )
    if resolved is None:
        return None
    path, data = resolved
    suffix = PurePosixPath(path).suffix.lower() or ".png"
    content_type = mimetypes.types_map.get(suffix, "application/octet-stream")
    checksum = hashlib.sha256(data).hexdigest()
    page = _page_number(block)
    rect = _bbox(block)
    asset_id = hashlib.sha256(
        f"{document_id}:{page}:{path}:{checksum}".encode()
    ).hexdigest()[:32]
    object_key = f"documents/{document_id}/reflow/assets/{asset_id}{suffix}"
    if write_asset is not None:
        write_asset(data, object_key, content_type)
    width, height = _asset_dimensions(data, suffix)
    kind: ReflowAssetKind = "vector" if suffix == ".svg" else "raster"
    return DocumentReflowAsset(
        id=asset_id,
        object_key=object_key,
        kind=kind,
        content_type=content_type,
        width=width,
        height=height,
        page_number=page,
        source_rect=rect,
        checksum=checksum,
    )


def _block_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "text").lower()
    if block_type == "table":
        return _as_text(block.get("table_body") or block.get("content"))
    if block_type in {"image", "chart"}:
        return _as_text(
            block.get(f"{block_type}_caption")
            or block.get("image_caption")
            or block.get("chart_caption")
            or block.get("caption")
            or block.get("content")
        )
    if block_type == "code":
        return _as_text(block.get("code_body") or block.get("content"))
    if block_type == "list":
        return _as_text(block.get("list_items") or block.get("content"))
    return _as_text(
        block.get("text")
        or block.get("content")
        or block.get("latex")
        or block.get("equation")
    )


def _heading_kind(text: str, level: int, index: int) -> ReflowBlockKind:
    normalized = _plain_text(text).lower().rstrip(":：")
    if normalized in {"abstract", "summary"}:
        return "abstract"
    if normalized in {"keywords", "key words", "index terms"}:
        return "keywords"
    if normalized in {"references", "bibliography"}:
        return "references"
    return "title" if index == 0 or level == 1 else "heading"


def _candidate(
    block: dict[str, Any],
    *,
    index: int,
    in_references: bool,
    before_body: bool,
    asset_id: str | None,
) -> _Candidate | None:
    block_type = str(block.get("type") or "text").lower()
    if block_type in _AUXILIARY_TYPES:
        return None
    raw = _block_text(block)
    span = _span(block, raw)
    status: ReflowPresentationStatus = "verbatim"
    heading_level: int | None = None
    group_id: str | None = None

    if block_type in {"image", "chart"}:
        caption, changed = _safe_markdown(raw)
        return _Candidate(
            kind="figure",
            markdown=caption or "Figure",
            heading_level=None,
            spans=(span,),
            presentation_status="repaired" if changed else "verbatim",
            asset_id=asset_id,
        )
    if block_type == "table":
        markdown, changed = _table_markdown(raw)
        return _Candidate(
            kind="table",
            markdown=markdown or "Table",
            heading_level=None,
            spans=(span,),
            presentation_status=(
                "degraded" if not markdown else "repaired" if changed else "verbatim"
            ),
        )
    if block_type == "equation":
        markdown, changed = _safe_markdown(raw, prose=False)
        if markdown and not markdown.startswith(("$$", "\\[")):
            markdown = f"$$\n{markdown}\n$$"
            changed = True
        return _Candidate(
            kind="equation",
            markdown=markdown or "Equation",
            heading_level=None,
            spans=(span,),
            presentation_status="degraded"
            if not markdown
            else "repaired"
            if changed
            else "verbatim",
        )
    if block_type == "code":
        markdown, changed = _safe_markdown(raw, prose=False)
        return _Candidate(
            kind="code",
            markdown=f"```\n{markdown}\n```" if markdown else "```\n```",
            heading_level=None,
            spans=(span,),
            presentation_status="repaired" if changed else "verbatim",
        )
    if block_type == "list":
        lines = [line.strip(" -•\t") for line in raw.splitlines() if line.strip()]
        markdown = "\n".join(f"- {line}" for line in lines)
        return _Candidate(
            kind="list",
            markdown=markdown or "- …",
            heading_level=None,
            spans=(span,),
            presentation_status="repaired",
        )

    markdown, changed = _safe_markdown(raw)
    if not markdown:
        return None
    try:
        level = int(block.get("text_level", 0) or 0)
    except (TypeError, ValueError):
        level = 0
    if level:
        heading_level = max(1, min(6, level))
        kind = _heading_kind(markdown, heading_level, index)
        if kind in {"title", "heading", "abstract", "keywords", "references"}:
            markdown = f"{'#' * heading_level} {markdown}"
    elif block_type == "page_footnote":
        kind = "footnote"
    elif in_references:
        kind = "references"
    elif before_body:
        kind = "authors"
        group_id = "paper-information"
    else:
        kind = "paragraph"
    return _Candidate(
        kind=kind,
        markdown=markdown,
        heading_level=heading_level,
        spans=(span,),
        presentation_status="degraded"
        if "�" in raw
        else "repaired"
        if changed
        else status,
        group_id=group_id,
    )


def _can_merge(previous: _Candidate, current: _Candidate) -> bool:
    if previous.kind != "paragraph" or current.kind != "paragraph":
        return False
    if previous.asset_id or current.asset_id:
        return False
    if _TERMINAL.search(previous.markdown.rstrip()):
        return False
    first = _plain_text(current.markdown)[:1]
    return bool(
        first
        and (
            first.islower()
            or previous.spans[-1].page_number != current.spans[0].page_number
        )
    )


def _merge_candidates(candidates: Iterable[_Candidate]) -> list[_Candidate]:
    merged: list[_Candidate] = []
    for candidate in candidates:
        if merged and _can_merge(merged[-1], candidate):
            previous = merged[-1]
            joined = f"{previous.markdown.rstrip()} {candidate.markdown.lstrip()}"
            merged[-1] = _Candidate(
                kind="paragraph",
                markdown=joined,
                heading_level=None,
                spans=(*previous.spans, *candidate.spans),
                presentation_status=(
                    "degraded"
                    if "degraded"
                    in {previous.presentation_status, candidate.presentation_status}
                    else "repaired"
                ),
                group_id=previous.group_id,
                asset_id=None,
            )
            continue
        merged.append(candidate)
    return merged


async def generate_document_reflow(
    *,
    document_id: str,
    title: str,
    pdf_bytes: bytes,
    write_asset: AssetWriter | None = None,
) -> DocumentReflowResult:
    client = MinerUClient()
    parsed = await client.parse_file(pdf_bytes, data_id=f"reflow-{document_id}")
    if parsed.archive_bytes is None:
        raise ValueError("mineru_reflow_archive_missing")
    archive = client.read_structured_archive(parsed.archive_bytes)

    return build_document_reflow(
        document_id=document_id,
        title=title,
        pdf_bytes=pdf_bytes,
        archive=archive,
        parser_revision=parsed.parser_version,
        write_asset=write_asset,
    )


def build_document_reflow(
    *,
    document_id: str,
    title: str,
    pdf_bytes: bytes,
    archive: MinerUArchive,
    parser_revision: str,
    write_asset: AssetWriter | None = None,
) -> DocumentReflowResult:
    """Convert stable MinerU reading-order output into the public reading AST."""

    del title  # MinerU's evidence, not supplied metadata, owns document structure.

    warnings: list[str] = []
    assets: list[DocumentReflowAsset] = []
    candidates: list[_Candidate] = []
    in_references = False
    before_body = True
    ordered = sorted(
        enumerate(archive.content_list),
        key=lambda item: (_page_number(item[1]), item[0]),
    )
    for _, provider_block in ordered:
        block = dict(provider_block)
        asset = _asset_from_block(
            archive=archive,
            block=block,
            document_id=document_id,
            write_asset=write_asset,
        )
        if asset is not None and all(existing.id != asset.id for existing in assets):
            assets.append(asset)
        candidate = _candidate(
            block,
            index=len(candidates),
            in_references=in_references,
            before_body=before_body,
            asset_id=asset.id if asset is not None else None,
        )
        if candidate is None:
            continue
        visible = _plain_text(candidate.markdown).lower().rstrip(":：")
        if candidate.kind == "references" or visible in {"references", "bibliography"}:
            in_references = True
        if candidate.kind in {"abstract", "keywords", "heading", "paragraph", "quote"}:
            before_body = False
        if candidate.kind == "figure" and asset is None:
            warnings.append(f"reflow_asset_missing:{candidate.spans[0].page_number}")
            candidate = _Candidate(
                kind=candidate.kind,
                markdown=candidate.markdown,
                heading_level=candidate.heading_level,
                spans=candidate.spans,
                presentation_status="degraded",
                group_id=candidate.group_id,
                asset_id=None,
            )
        candidates.append(candidate)

    if not candidates:
        raise ValueError("mineru_reflow_content_empty")
    merged = _merge_candidates(candidates)
    blocks: list[DocumentReflowBlock] = []
    for index, candidate in enumerate(merged):
        spans = list(candidate.spans)
        identity = ":".join(
            f"{span.page_number}:{span.source_rect.x:.4f}:{span.source_rect.y:.4f}"
            for span in spans
        )
        blocks.append(
            DocumentReflowBlock(
                id=hashlib.sha256(
                    f"{document_id}:{index}:{identity}:{candidate.markdown}".encode()
                ).hexdigest()[:32],
                index=index,
                kind=candidate.kind,
                render_markdown=candidate.markdown,
                group_id=candidate.group_id,
                heading_level=candidate.heading_level,
                source_spans=spans,
                presentation_status=candidate.presentation_status,
                asset_id=candidate.asset_id,
            )
        )

    return DocumentReflowResult(
        document_id=document_id,
        source_hash=hashlib.sha256(pdf_bytes).hexdigest(),
        pipeline_revision=REFLOW_PIPELINE_REVISION,
        parser_revision=parser_revision,
        blocks=blocks,
        assets=assets,
        warnings=warnings,
    )
