"""Stable classification of provider failures."""

from __future__ import annotations

import openai
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from app.llm.backend import LLMUsageSettlementError
from app.shared.domain import AppError, FailureKind


def _causes(error: BaseException) -> tuple[BaseException, ...]:
    values: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        values.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return tuple(values)


def _details(*, stage: str, status_code: int | None = None) -> dict[str, object]:
    return {
        "stage": stage,
        **({"provider_status": status_code} if status_code is not None else {}),
    }


def classify_llm_error(error: BaseException, *, stage: str) -> AppError:
    if isinstance(error, AppError):
        return error
    causes = _causes(error)
    if isinstance(error, ModelHTTPError):
        status_code = error.status_code
        if status_code in {408, 504}:
            return AppError(
                code="llm_stream_timeout",
                message="The model stopped responding before the operation completed.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                details=_details(stage=stage, status_code=status_code),
                retryable=True,
            )
        if status_code == 429:
            return AppError(
                code="llm_provider_rate_limited",
                message="The model provider is temporarily rate limited.",
                kind=FailureKind.RATE_LIMITED,
                details=_details(stage=stage, status_code=status_code),
                retryable=True,
            )
        if status_code in {401, 403}:
            return AppError(
                code="llm_provider_authentication_failed",
                message="The model provider is not configured correctly.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                details=_details(stage=stage, status_code=status_code),
                retryable=False,
            )
        if 400 <= status_code < 500:
            return AppError(
                code="llm_provider_request_rejected",
                message="The model provider rejected this operation.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                details=_details(stage=stage, status_code=status_code),
                retryable=False,
            )
        return AppError(
            code="llm_provider_unavailable",
            message="The model provider is temporarily unavailable.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage, status_code=status_code),
            retryable=True,
        )
    if isinstance(error, ContentFilterError):
        return AppError(
            code="llm_content_filtered",
            message="The model provider could not process this content.",
            kind=FailureKind.UNPROCESSABLE,
            details=_details(stage=stage),
            retryable=False,
        )
    if isinstance(error, UsageLimitExceeded):
        return AppError(
            code="llm_agent_usage_limit_exceeded",
            message="The response exceeded the model operation limit.",
            kind=FailureKind.UNPROCESSABLE,
            details=_details(stage=stage),
            retryable=False,
        )
    if isinstance(error, UnexpectedModelBehavior):
        return AppError(
            code="llm_provider_response_invalid",
            message="The model provider returned an invalid response.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage),
            retryable=True,
        )
    if any(isinstance(item, openai.APITimeoutError) for item in causes):
        return AppError(
            code="llm_stream_timeout",
            message="The model stopped responding before the operation completed.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage),
            retryable=True,
        )
    if any(isinstance(item, openai.RateLimitError) for item in causes):
        return AppError(
            code="llm_provider_rate_limited",
            message="The model provider is temporarily rate limited.",
            kind=FailureKind.RATE_LIMITED,
            details=_details(stage=stage),
            retryable=True,
        )
    if any(isinstance(item, openai.AuthenticationError) for item in causes):
        return AppError(
            code="llm_provider_authentication_failed",
            message="The model provider is not configured correctly.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage),
            retryable=False,
        )
    if any(isinstance(item, openai.BadRequestError) for item in causes):
        return AppError(
            code="llm_provider_request_rejected",
            message="The model provider rejected this operation.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage),
            retryable=False,
        )
    if isinstance(error, ModelAPIError) or any(
        isinstance(item, openai.APIConnectionError) for item in causes
    ):
        return AppError(
            code="llm_provider_unavailable",
            message="The model provider is temporarily unavailable.",
            kind=FailureKind.DEPENDENCY_FAILURE,
            details=_details(stage=stage),
            retryable=True,
        )
    if isinstance(error, LLMUsageSettlementError):
        return AppError(
            code="llm_usage_settlement_failed",
            message="Model usage could not be recorded safely.",
            kind=FailureKind.UNAVAILABLE,
            details=_details(stage=stage),
            retryable=True,
        )
    return AppError(
        code="llm_operation_failed",
        message="The model operation failed unexpectedly.",
        kind=FailureKind.DEPENDENCY_FAILURE,
        details=_details(stage=stage),
        retryable=True,
    )
