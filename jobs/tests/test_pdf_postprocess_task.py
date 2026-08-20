from __future__ import annotations

from unittest.mock import patch

from scholens_ai import EMBEDDING_MODEL_REVISION
from src.tasks import postprocess_pdf_task


def test_pdf_postprocess_adds_local_embedding_to_callback() -> None:
    with (
        patch("src.tasks._claim_job", return_value=True),
        patch("src.tasks.embed_text", return_value=[0.25] * 384),
        patch("src.tasks._deliver_webhook", return_value=True) as deliver,
    ):
        result = postprocess_pdf_task.apply(
            args=(
                "https://server.example/callback",
                None,
                "semantic paper text",
                "a" * 64,
            ),
            task_id="00000000-0000-4000-8000-000000000001",
            throw=True,
        ).get()

    payload = deliver.call_args.args[1]
    assert payload["embedding"] == [0.25] * 384
    assert payload["embedding_model_revision"] == EMBEDDING_MODEL_REVISION
    assert payload["embedding_source_digest"] == "a" * 64
    assert result["status"] == "completed"


def test_pdf_postprocess_embedding_failure_does_not_block_indexing() -> None:
    with (
        patch("src.tasks._claim_job", return_value=True),
        patch("src.tasks.embed_text", side_effect=RuntimeError("model failed")),
        patch("src.tasks._deliver_webhook", return_value=True) as deliver,
    ):
        postprocess_pdf_task.apply(
            args=(
                "https://server.example/callback",
                None,
                "semantic paper text",
                "b" * 64,
            ),
            task_id="00000000-0000-4000-8000-000000000002",
            throw=True,
        ).get()

    assert deliver.call_args.args[1] == {
        "task_id": "00000000-0000-4000-8000-000000000002"
    }
