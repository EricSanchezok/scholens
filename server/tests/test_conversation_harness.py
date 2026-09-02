from __future__ import annotations

from types import SimpleNamespace

from app.llm.conversation_harness import (
    ConversationStepClassifier,
    ConversationStepRole,
)
from pydantic_ai.messages import ToolCallPart


def test_classifier_treats_plain_text_as_terminal() -> None:
    step = ConversationStepClassifier().classify(
        next_node=SimpleNamespace(),
        text_chunks=("A ", "direct answer."),
    )

    assert step.role == ConversationStepRole.TERMINAL
    assert step.text == "A direct answer."
    assert step.tool_names == ()


def test_classifier_treats_text_with_tools_as_progress() -> None:
    step = ConversationStepClassifier().classify(
        next_node=SimpleNamespace(),
        text_chunks=("I will search.",),
        tool_parts=(
            ToolCallPart(
                tool_name="search_saved_papers",
                args={"query": "topic"},
            ),
        ),
    )

    assert step.role == ConversationStepRole.PROGRESS
    assert step.tool_names == ("search_saved_papers",)


def test_classifier_rejects_removed_output_tool() -> None:
    step = ConversationStepClassifier().classify(
        next_node=SimpleNamespace(),
        text_chunks=(),
        tool_parts=(ToolCallPart(tool_name="final_answer", args={}),),
    )

    assert step.role == ConversationStepRole.PROTOCOL_ERROR


def test_classifier_marks_empty_model_step() -> None:
    step = ConversationStepClassifier().classify(
        next_node=SimpleNamespace(),
        text_chunks=(),
    )

    assert step.role == ConversationStepRole.EMPTY
