from __future__ import annotations

import json
from unittest.mock import patch

import requests
from scholens_ai import EMBEDDING_MODEL_REVISION, decode_passage_embedding_artifact
from src.tasks import _deliver_pdf_postprocess_webhook, postprocess_pdf_task


def _response(status: int, body: dict[str, object]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://server.example/internal/v1/jobs/postprocess"
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()  # noqa: SLF001 - response fixture
    response._content_consumed = True  # noqa: SLF001 - response fixture
    return response


def test_pdf_postprocess_adds_local_embedding_to_callback() -> None:
    with (
        patch("src.tasks._claim_job", return_value=True),
        patch("src.tasks.embed_text", return_value=[0.25] * 384),
        patch(
            "src.tasks._deliver_pdf_postprocess_webhook", return_value=True
        ) as deliver,
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
        patch(
            "src.tasks._deliver_pdf_postprocess_webhook", return_value=True
        ) as deliver,
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


def test_pdf_postprocess_uploads_bounded_passage_embedding_artifact() -> None:
    class _Embedder:
        def embed_passages(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] + [0.0] * 383 for _text in texts]

    with (
        patch("src.tasks._claim_job", return_value=True),
        patch("src.tasks.try_local_embedder", return_value=_Embedder()),
        patch(
            "src.tasks.s3_service.download_file_to_bytes",
            return_value=b"one\ntwo\nthree\nfour\nfive\nsix",
        ),
        patch("src.tasks.s3_service.upload_bytes_to_key") as upload,
        patch(
            "src.tasks._deliver_pdf_postprocess_webhook", return_value=True
        ) as deliver,
    ):
        result = postprocess_pdf_task.apply(
            kwargs={
                "callback_url": "https://server.example/callback",
                "parser_markdown_s3_key": "documents/a/canonical.md",
            },
            task_id="00000000-0000-4000-8000-000000000003",
            throw=True,
        ).get()

    artifact = upload.call_args.args[0]
    decoded = decode_passage_embedding_artifact(artifact)
    metadata = deliver.call_args.args[1]["passage_embedding_artifact"]
    assert decoded.model_revision == EMBEDDING_MODEL_REVISION
    assert len(decoded.records) == 2
    assert metadata["passage_count"] == 2
    assert metadata["byte_size"] == len(artifact)
    assert result["status"] == "completed"


def test_old_server_retries_once_without_passage_artifact() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "extra_forbidden",
                        "location": ["body", "passage_embedding_artifact"],
                    }
                ]
            },
        },
    )
    accepted = _response(200, {"status": "accepted"})
    payload = {
        "task_id": "00000000-0000-4000-8000-000000000004",
        "passage_embedding_artifact": {"storage_key": "jobs/example"},
    }

    with patch("src.tasks.post_signed_json", side_effect=[rejected, accepted]) as post:
        delivered = _deliver_pdf_postprocess_webhook(
            "https://server.example/internal/v1/jobs/postprocess",
            payload,
            task_id=str(payload["task_id"]),
        )

    assert delivered is True
    assert post.call_count == 2
    assert "passage_embedding_artifact" not in post.call_args_list[1].args[1]
    assert "passage_embedding_artifact" in payload


def test_postprocess_compatibility_retry_rejects_mixed_validation_errors() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "extra_forbidden",
                        "location": ["body", "passage_embedding_artifact"],
                    },
                    {"type": "missing", "location": ["body", "task_id"]},
                ]
            },
        },
    )

    with patch("src.tasks.post_signed_json", return_value=rejected) as post:
        delivered = _deliver_pdf_postprocess_webhook(
            "https://server.example/internal/v1/jobs/postprocess",
            {"passage_embedding_artifact": {}},
            task_id="task-4",
        )

    assert delivered is False
    post.assert_called_once()
