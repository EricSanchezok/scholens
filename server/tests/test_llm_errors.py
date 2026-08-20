from pydantic_ai.exceptions import UsageLimitExceeded

from app.llm.errors import classify_llm_error
from app.shared.domain import FailureKind


def test_usage_limit_has_stable_orchestration_error() -> None:
    error = classify_llm_error(
        UsageLimitExceeded("The next request would exceed the tool_calls_limit"),
        stage="conversation_agent",
    )

    assert error.code == "agent_orchestration_limit_exceeded"
    assert error.kind is FailureKind.CONFLICT
    assert error.retryable is False
    assert error.details == {"stage": "conversation_agent"}
    assert "tool_calls_limit" not in error.message
