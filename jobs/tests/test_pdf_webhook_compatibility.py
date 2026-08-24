"""Rolling-deploy compatibility for the additive PDF page-count result."""

from __future__ import annotations

import json
from unittest.mock import patch

import requests

from src.tasks import _deliver_pdf_webhook


def _response(status: int, body: dict[str, object]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://server.example/internal/v1/jobs/pdf"
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()  # noqa: SLF001 - response fixture
    response._content_consumed = True  # noqa: SLF001 - response fixture
    return response


def test_old_consumer_extra_page_count_retries_once_without_additive_field() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "extra_forbidden",
                        "location": ["body", "result", "page_count"],
                    }
                ]
            },
        },
    )
    accepted = _response(200, {"status": "accepted"})
    payload = {
        "task_id": "task-1",
        "status": "completed",
        "result": {"success": True, "job_id": "task-1", "page_count": 3},
    }

    with patch(
        "src.tasks.post_signed_json",
        side_effect=[rejected, accepted],
    ) as post:
        delivered = _deliver_pdf_webhook(
            "https://server.example/internal/v1/jobs/pdf",
            payload,
            task_id="task-1",
        )

    assert delivered is True
    assert post.call_count == 2
    fallback = post.call_args_list[1].args[1]
    assert "page_count" not in fallback["result"]
    assert payload["result"]["page_count"] == 3


def test_nonmatching_422_does_not_hide_validation_failure() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "greater_than_equal",
                        "location": ["body", "result", "page_count"],
                    }
                ]
            },
        },
    )
    payload = {
        "task_id": "task-1",
        "status": "completed",
        "result": {"success": True, "job_id": "task-1", "page_count": 0},
    }

    with patch("src.tasks.post_signed_json", return_value=rejected) as post:
        delivered = _deliver_pdf_webhook(
            "https://server.example/internal/v1/jobs/pdf",
            payload,
            task_id="task-1",
        )

    assert delivered is False
    post.assert_called_once()


def test_mixed_page_count_and_other_validation_errors_do_not_retry() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "extra_forbidden",
                        "location": ["body", "result", "page_count"],
                    },
                    {
                        "type": "missing",
                        "location": ["body", "result", "raw_content"],
                    },
                ]
            },
        },
    )
    payload = {
        "task_id": "task-1",
        "status": "completed",
        "result": {"success": True, "job_id": "task-1", "page_count": 3},
    }

    with patch("src.tasks.post_signed_json", return_value=rejected) as post:
        delivered = _deliver_pdf_webhook(
            "https://server.example/internal/v1/jobs/pdf",
            payload,
            task_id="task-1",
        )

    assert delivered is False
    post.assert_called_once()


def test_page_count_error_outside_callback_body_does_not_retry() -> None:
    rejected = _response(
        422,
        {
            "code": "request_validation_failed",
            "details": {
                "errors": [
                    {
                        "type": "extra_forbidden",
                        "location": ["query", "result", "page_count"],
                    }
                ]
            },
        },
    )
    payload = {
        "task_id": "task-1",
        "status": "completed",
        "result": {"success": True, "job_id": "task-1", "page_count": 3},
    }

    with patch("src.tasks.post_signed_json", return_value=rejected) as post:
        delivered = _deliver_pdf_webhook(
            "https://server.example/internal/v1/jobs/pdf",
            payload,
            task_id="task-1",
        )

    assert delivered is False
    post.assert_called_once()
