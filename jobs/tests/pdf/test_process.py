from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pymupdf
import pytest

from src.pdf.process import analyze_in_process, run_parser_process


def test_timeout_terminates_and_reaps_a_parser_ignoring_sigterm(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    command = [
        sys.executable,
        "-c",
        "import os,signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)",
    ]
    with pytest.raises(TimeoutError):
        asyncio.run(run_parser_process(command, timeout=1.0))
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cancellation_reaps_the_parser_before_returning(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"

    async def run() -> None:
        task = asyncio.create_task(
            run_parser_process(
                [
                    sys.executable,
                    "-c",
                    "import os,time,pathlib; "
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)",
                ],
                timeout=60,
            )
        )
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_analysis_crosses_process_boundary_with_bounded_preview(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=14400, height=14400)
        page.insert_text((100, 100), "A large physical page with small preview")
        pdf.save(source)
    result = asyncio.run(analyze_in_process(str(source), timeout=15))
    assert result.page_count == 1
    assert "large physical page" in result.markdown
    assert result.preview_bytes is not None
    from io import BytesIO
    from PIL import Image

    with Image.open(BytesIO(result.preview_bytes)) as image:
        assert image.width <= 800
        assert image.width * image.height <= 800 * 1600
