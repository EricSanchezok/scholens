from __future__ import annotations


from app.llm.token_credits import llm_usage_context, settle_token_usage


def _settle() -> bool:
    return settle_token_usage(
        provider="deepseek",
        model="standard-model",
        ai_profile="standard",
        thinking="disabled",
        thinking_effort="none",
        profile_revision="profile-v1",
        prompt_tokens=100,
        completion_tokens=80,
        reasoning_tokens=50,
        total_tokens=180,
        provider_request_id="request-1",
        idempotency_key="job-1:metadata",
    )


def test_byok_does_not_write_token_events_or_weekly_totals() -> None:
    with llm_usage_context(user_id=42, feature="metadata", operation_id="job-1"):
        assert _settle() is False
