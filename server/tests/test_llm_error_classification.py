from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
import httpx
import openai
import pytest

from app.llm.errors import classify_llm_error
from app.shared.domain import FailureKind


@pytest.mark.parametrize(
    ("status", "code", "kind", "retryable"),
    [
        (
            401,
            "llm_provider_authentication_failed",
            FailureKind.DEPENDENCY_FAILURE,
            False,
        ),
        (429, "llm_provider_rate_limited", FailureKind.RATE_LIMITED, True),
        (500, "llm_provider_unavailable", FailureKind.DEPENDENCY_FAILURE, True),
        (504, "llm_stream_timeout", FailureKind.DEPENDENCY_FAILURE, True),
    ],
)
def test_classifies_wrapped_model_http_errors(
    status: int,
    code: str,
    kind: FailureKind,
    retryable: bool,
) -> None:
    result = classify_llm_error(
        ModelHTTPError(status, "deepseek:test", {"secret": "must-not-escape"}),
        stage="conversation_agent",
    )

    assert result.code == code
    assert result.kind is kind
    assert result.retryable is retryable
    assert result.details == {
        "stage": "conversation_agent",
        "provider_status": status,
    }
    assert "secret" not in repr(result.details)


@pytest.mark.parametrize(
    ("error", "code", "kind", "retryable"),
    [
        (
            ModelAPIError("deepseek:test", "connection failed"),
            "llm_provider_unavailable",
            FailureKind.DEPENDENCY_FAILURE,
            True,
        ),
        (
            UnexpectedModelBehavior("invalid tool response", "private response"),
            "llm_provider_response_invalid",
            FailureKind.DEPENDENCY_FAILURE,
            True,
        ),
        (
            ContentFilterError("filtered", "private response"),
            "llm_content_filtered",
            FailureKind.UNPROCESSABLE,
            False,
        ),
        (
            UsageLimitExceeded("request limit"),
            "agent_orchestration_limit_exceeded",
            FailureKind.CONFLICT,
            False,
        ),
    ],
)
def test_classifies_pydantic_ai_runtime_errors(
    error: Exception,
    code: str,
    kind: FailureKind,
    retryable: bool,
) -> None:
    result = classify_llm_error(error, stage="conversation_agent")

    assert result.code == code
    assert result.kind is kind
    assert result.retryable is retryable
    assert result.details == {"stage": "conversation_agent"}


def test_classifies_provider_cause_before_generic_model_wrapper() -> None:
    wrapped = ModelAPIError("deepseek:test", "request failed")
    wrapped.__cause__ = openai.BadRequestError(
        "private provider response",
        response=httpx.Response(
            400,
            request=httpx.Request("POST", "https://provider.invalid/chat"),
        ),
        body={"secret": "must-not-escape"},
    )

    result = classify_llm_error(wrapped, stage="conversation_agent")

    assert result.code == "llm_provider_request_rejected"
    assert result.retryable is False
    assert result.details == {"stage": "conversation_agent"}
