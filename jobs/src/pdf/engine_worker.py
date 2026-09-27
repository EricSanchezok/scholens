"""Private subprocess entry point; no provider, storage or Celery dependencies."""

from __future__ import annotations

import ctypes
from dataclasses import replace
import os
from pathlib import Path
import signal
import sys


def main() -> None:
    # A hard-killed Celery child cannot run finally. Linux kills its parser too;
    # checking the original parent closes the race before prctl is installed.
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot supervise parser parent")
    if os.getppid() != int(sys.argv[2]):
        raise SystemExit(75)

    from pydantic import TypeAdapter
    from scholens_job_contracts import require_pdf_callback_content_size
    from src.pdf.local import (
        analyze_pdf_path,
        extract_markdown_markitdown,
        extract_markdown_pymupdf4llm,
    )
    from src.pdf.models import LocalPDFAnalysis, ParsedDocument
    from src.pdf.process import MAX_RESULT_BYTES, MAX_PREVIEW_BYTES, ParserRequest

    path = Path(sys.argv[1])
    request = ParserRequest.model_validate_json(path.read_bytes())
    result: LocalPDFAnalysis | ParsedDocument
    if request.operation == "analyze":
        result = analyze_pdf_path(request.source_path)
        if (
            result.preview_bytes is not None
            and len(result.preview_bytes) <= MAX_PREVIEW_BYTES
        ):
            (path.parent / "preview.webp").write_bytes(result.preview_bytes)
        result = replace(result, preview_bytes=None)
        encoded = TypeAdapter(LocalPDFAnalysis).dump_json(result)
    else:
        if request.operation == "pymupdf4llm":
            result = extract_markdown_pymupdf4llm(
                request.source_path, parser_version=request.parser_version
            )
        else:
            result = extract_markdown_markitdown(
                request.source_path,
                parser_version=request.parser_version,
                fallback_offsets=request.fallback_offsets,
            )
        encoded = TypeAdapter(ParsedDocument).dump_json(result)
    require_pdf_callback_content_size(
        raw_content=result.markdown, page_offset_map=result.page_offset_map
    )
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("Parser result exceeds its file budget")
    (path.parent / "result.json").write_bytes(encoded)


if __name__ == "__main__":
    main()
