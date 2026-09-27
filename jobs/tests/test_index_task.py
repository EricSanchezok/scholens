from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from scholens_ai import TokenProjection
from scholens_ai.inference_client import EmbeddingUnavailable

from src import tasks
from src.execution_delivery import DeliveryUnavailable


@pytest.mark.parametrize("failure", [None, "receipt", "inference", "source"])
def test_independent_index_preserves_readability_and_retries_only_transient_work(
    monkeypatch, failure
):
    runtime = MagicMock()
    runtime.job_id = str(uuid4())
    monkeypatch.setattr(
        tasks, "run_fenced_task", lambda _task, **kwargs: kwargs["work"](runtime)
    )
    storage = MagicMock()
    storage.download_bounded_bytes.return_value = b"text"
    monkeypatch.setattr(tasks, "s3_service", storage)
    model = MagicMock(revision="test-v1")
    monkeypatch.setattr(tasks, "configured_embedder", lambda: model)
    monkeypatch.setattr(tasks, "load_passage_tokenizer", MagicMock())
    projection = TokenProjection.model_construct(
        content_digest="a" * 64, model_revision="test-v1", spans=[], vectors=""
    )
    build = MagicMock(return_value=projection)
    monkeypatch.setattr(tasks, "build_checkpointed_projection", build)
    old_callback = MagicMock()
    monkeypatch.setattr(tasks, "_deliver_webhook", old_callback)
    if failure == "receipt":
        runtime.complete.side_effect = DeliveryUnavailable("receipt_lost")
    elif failure == "inference":
        build.side_effect = EmbeddingUnavailable("owner_down")
    elif failure == "source":
        build.side_effect = ValueError("source_changed")
    kwargs = dict(
        callback_url=f"https://server/internal/v1/jobs/{runtime.job_id}/complete",
        parser_markdown_s3_key="canonical.md",
        content_digest="a" * 64,
        model_revision="test-v1",
    )
    if failure in {"receipt", "inference"}:
        with pytest.raises(DeliveryUnavailable):
            tasks.index_document_task.run(**kwargs)
        runtime.fail.assert_not_called()
    else:
        result = tasks.index_document_task.run(**kwargs)
        assert result["status"] == ("failed" if failure == "source" else "completed")
    old_callback.assert_not_called()
    storage.download_bounded_bytes.assert_called_once_with(
        "canonical.md", max_bytes=40 * 1024 * 1024
    )
