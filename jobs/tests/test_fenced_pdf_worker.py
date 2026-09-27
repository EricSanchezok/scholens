from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.execution_delivery import DeliveryUnavailable, FencedExecution
from src.schemas import PDFProcessingResult
from src.tasks import _process_pdf_task


@pytest.mark.parametrize("receipt_lost", [False, True])
def test_basic_pdf_is_readable_without_ai_and_delivery_failure_never_recomputes(
    tmp_path, receipt_lost
):
    job_id = str(uuid4())
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-synthetic")
    task = MagicMock()
    task.request.id = job_id
    execution = MagicMock(spec=FencedExecution)
    execution.complete.return_value = True
    if receipt_lost:
        execution.complete.side_effect = DeliveryUnavailable("lost receipt")
    parse = AsyncMock(
        return_value=PDFProcessingResult(
            success=True,
            job_id=job_id,
            raw_content="Readable original text",
            metadata=None,
            page_offset_map={1: [0, 22]},
            parser_backend="pymupdf4llm",
            parser_quality="text_only",
            parser_version="fixture-v1",
        )
    )
    with (
        patch("src.tasks.process_pdf_file", parse),
        patch("src.tasks._claim_job_with_retry") as old_claim,
        patch("src.tasks._deliver_webhook") as old_failure,
        patch("src.tasks._deliver_pdf_webhook") as old_complete,
    ):

        def run():
            return _process_pdf_task(
                task,
                "source.pdf",
                f"https://server/internal/v1/jobs/{job_id}/complete",
                "progress",
                None,
                "credential",
                local_pdf_path=str(source),
                execution=execution,
            )

        if receipt_lost:
            with pytest.raises(DeliveryUnavailable):
                run()
        else:
            assert run()["status"] == "completed"
        assert parse.await_count == 1
        assert parse.call_args.kwargs["skip_metadata_extraction"] is True
        assert execution.complete.call_args.args[0]["result"]["metadata"] is None
        old_claim.assert_not_called()
        old_failure.assert_not_called()
        old_complete.assert_not_called()
    assert not source.exists()
