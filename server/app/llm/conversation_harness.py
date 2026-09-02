"""Execution and publication boundaries for the conversation harness.

The Pydantic AI graph remains the execution engine.  This module only gives the
Scholens layer a small, deterministic vocabulary for classifying a completed
model step and publishing ordinary text as a grounded answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import re
from typing import Any

from app.llm.citation_normalizer import CitationNormalizer
from app.llm.grounded_answer import GroundedAnswerInspection, inspect_grounded_answer
from app.modules.conversations.application.contracts.answer_packet import AnswerPacket
from pydantic_ai.messages import ToolCallPart


class ConversationStepRole(StrEnum):
    """Stable roles used by the Scholens presentation layer."""

    PROGRESS = "progress"
    TERMINAL = "terminal"
    EMPTY = "empty"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(frozen=True, slots=True)
class ConversationStep:
    role: ConversationStepRole
    text: str
    tool_names: tuple[str, ...]
    finish_reason: str | None = None
    text_chunks: tuple[str, ...] = ()


class ConversationStepClassifier:
    """Classify one complete model response without phrase heuristics."""

    def classify(
        self,
        *,
        next_node: Any,
        text_chunks: Sequence[str],
        tool_parts: Sequence[ToolCallPart] = (),
        finish_reason: str | None = None,
    ) -> ConversationStep:
        text = "".join(text_chunks)
        tool_names = tuple(
            part.tool_name for part in tool_parts if isinstance(part, ToolCallPart)
        )
        if "final_answer" in tool_names:
            return ConversationStep(
                role=ConversationStepRole.PROTOCOL_ERROR,
                text="",
                tool_names=tool_names,
                finish_reason=finish_reason,
                text_chunks=tuple(text_chunks),
            )
        if tool_names:
            return ConversationStep(
                role=ConversationStepRole.PROGRESS,
                text=text,
                tool_names=tool_names,
                finish_reason=finish_reason,
                text_chunks=tuple(text_chunks),
            )
        if text.strip() and next_node is not None:
            return ConversationStep(
                role=ConversationStepRole.TERMINAL,
                text=text,
                tool_names=(),
                finish_reason=finish_reason,
                text_chunks=tuple(text_chunks),
            )
        return ConversationStep(
            role=ConversationStepRole.EMPTY,
            text=text,
            tool_names=(),
            finish_reason=finish_reason,
            text_chunks=tuple(text_chunks),
        )


class AnswerPublicationPolicy:
    """Turn ordinary model text into one sanitized grounded inspection."""

    def publish(
        self,
        raw_content: str,
        packet: AnswerPacket,
        *,
        nonce: str,
        normalizer: CitationNormalizer | None = None,
        private_protocol_detector: Any | None = None,
    ) -> GroundedAnswerInspection:
        if private_protocol_detector is not None and private_protocol_detector(
            raw_content
        ):
            raise RuntimeError("Model output contains private citation protocol prose")
        if normalizer is None:
            inspection = inspect_grounded_answer(
                raw_content,
                packet.sources,
                nonce=nonce,
            )
        else:
            inspection = normalizer.normalize(
                raw_content,
                packet.sources,
                nonce=nonce,
            ).inspection
        # Visible citation labels are never part of Scholens' public answer.  This
        # is a deterministic publication cleanup, not a model retry condition.
        cleaned = re.sub(
            r"\[A?\d+(?:\s*,\s*A?\d+)*\]",
            "",
            inspection.visible_content,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned != inspection.visible_content:
            inspection = replace(inspection, visible_content=cleaned)
        return inspection


__all__ = [
    "AnswerPublicationPolicy",
    "ConversationStep",
    "ConversationStepClassifier",
    "ConversationStepRole",
]
