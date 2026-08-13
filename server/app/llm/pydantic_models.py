"""Pydantic AI model construction for Scholens conversation workloads."""

from __future__ import annotations

from app.shared.domain.enums import ReasoningLevel
from pydantic_ai.models import Model
from scholens_ai import AIProfile, AIProfileName, build_model, resolve_profile


def profile_for_reasoning(reasoning_level: ReasoningLevel) -> AIProfile:
    return resolve_profile(
        AIProfileName.DEEP
        if reasoning_level is ReasoningLevel.DEEP
        else AIProfileName.STANDARD
    )


def build_chat_model(
    reasoning_level: ReasoningLevel,
    *,
    max_output_tokens: int | None = None,
) -> Model:
    """Build the model selected by the Scholens standard/deep profile."""
    return build_model(
        profile_for_reasoning(reasoning_level),
        max_output_tokens=max_output_tokens,
    )


__all__ = ["build_chat_model", "profile_for_reasoning"]
