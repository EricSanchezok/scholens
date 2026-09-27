"""Supervised, file-based local parser boundary (also works in Celery children)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from scholens_job_contracts import require_pdf_callback_content_size

from src.pdf.models import LocalPDFAnalysis, ParsedDocument, ParserContentError

MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_BYTES = 512 * 1024


class ParserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["analyze", "pymupdf4llm", "markitdown"]
    source_path: str
    parser_version: str = ""
    fallback_offsets: dict[int, list[int]] = Field(default_factory=dict)


async def run_parser_process(command: list[str], *, timeout: float) -> None:
    """Never return from timeout/cancellation while the parser is still alive."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout):
            code = await process.wait()
        if code != 0:
            raise ParserContentError("Local parser process failed")
    finally:
        # Kill the group as well as the immediate child: a parser may have
        # created a helper. Reap before removing its working directory.
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=0.5)
            except TimeoutError:
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise ParserContentError("Local parser output exceeds its bound")
    return content


async def _execute(
    request: ParserRequest, *, timeout: float
) -> tuple[bytes, bytes | None]:
    with tempfile.TemporaryDirectory(prefix="scholens-parser-") as directory:
        root = Path(directory)
        request_path = root / "request.json"
        request_path.write_bytes(request.model_dump_json().encode())
        await run_parser_process(
            [
                sys.executable,
                "-m",
                "src.pdf.engine_worker",
                str(request_path),
                str(os.getpid()),
            ],
            timeout=timeout,
        )
        preview_path = root / "preview.webp"
        return (
            _read_bounded(root / "result.json", MAX_RESULT_BYTES),
            _read_bounded(preview_path, MAX_PREVIEW_BYTES)
            if preview_path.exists()
            else None,
        )


async def analyze_in_process(
    pdf_path: str, *, timeout: float = 120
) -> LocalPDFAnalysis:
    content, preview = await _execute(
        ParserRequest(operation="analyze", source_path=str(Path(pdf_path).resolve())),
        timeout=timeout,
    )
    result = TypeAdapter(LocalPDFAnalysis).validate_json(content)
    require_pdf_callback_content_size(
        raw_content=result.markdown, page_offset_map=result.page_offset_map
    )
    return replace(result, preview_bytes=preview)


async def extract_in_process(
    pdf_path: str,
    *,
    engine: Literal["pymupdf4llm", "markitdown"],
    parser_version: str,
    fallback_offsets: dict[int, list[int]] | None = None,
    timeout: float = 120,
) -> ParsedDocument:
    content, _ = await _execute(
        ParserRequest(
            operation=engine,
            source_path=str(Path(pdf_path).resolve()),
            parser_version=parser_version,
            fallback_offsets=fallback_offsets or {},
        ),
        timeout=timeout,
    )
    result = TypeAdapter(ParsedDocument).validate_json(content)
    require_pdf_callback_content_size(
        raw_content=result.markdown, page_offset_map=result.page_offset_map
    )
    return result
