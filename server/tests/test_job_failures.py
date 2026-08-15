from __future__ import annotations

import pytest

from app.modules.jobs.application.failures import actionable_job_failure


@pytest.mark.parametrize(
    ("code", "retryable", "required_integration"),
    [
        ("mineru_credential_required", True, "mineru"),
        ("mineru_credential_invalid", True, "mineru"),
        ("mineru_rate_limited", True, None),
        ("mineru_unavailable", True, None),
        ("mineru_content_insufficient", False, None),
        ("mineru_response_unsafe", False, None),
    ],
)
def test_actionable_mineru_failures_preserve_product_semantics(
    code: str,
    retryable: bool,
    required_integration: str | None,
) -> None:
    failure = actionable_job_failure(code)

    assert failure is not None
    assert failure.code == code
    assert failure.retryable is retryable
    assert failure.required_integration == required_integration
