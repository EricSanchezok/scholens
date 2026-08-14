from __future__ import annotations

from uuid import uuid4

import pytest
from app.llm.follow_up_suggestions import (
    FollowUpSuggestionSet,
    SuggestionSeed,
    build_follow_up_prompt,
)
from pydantic import ValidationError


def _seed() -> SuggestionSeed:
    return SuggestionSeed(
        turn_id=uuid4(),
        user_query="How does retrieval work?",
        locale="en",
        recent_selected_turns=(
            ("What is grounding?", "Grounding connects an answer to evidence."),
        ),
        scope_titles=("Authorized project", "Verified paper"),
    )


def test_structured_suggestions_are_normalized_and_unique() -> None:
    suggestions = FollowUpSuggestionSet(
        deepen="  What   evidence is missing?  ",
        compare_or_verify="How does this compare?",
        practical_application="How would I apply it?",
    )

    assert suggestions.deepen == "What evidence is missing?"

    with pytest.raises(ValidationError):
        FollowUpSuggestionSet(
            deepen="Same?",
            compare_or_verify="same?",
            practical_application="Apply?",
        )


def test_prompt_uses_only_the_parallel_sidecar_allowlist() -> None:
    prompt = build_follow_up_prompt(_seed())

    assert "How does retrieval work?" in prompt
    assert "Grounding connects an answer to evidence." in prompt
    assert "Authorized project" in prompt
    assert "Verified paper" in prompt
    assert "selected_final_answer" not in prompt
    assert "tool_name" not in prompt
    assert "trace" not in prompt
    assert len(prompt) <= 12_000


def test_prompt_drops_history_before_truncating_current_question() -> None:
    seed = SuggestionSeed(
        turn_id=uuid4(),
        user_query="Q" * 20_000,
        locale="en",
        recent_selected_turns=(("old", "A" * 8_000),),
        scope_titles=("S" * 8_000,),
    )

    prompt = build_follow_up_prompt(seed)

    assert 'recent_selected_turns": []' in prompt
    assert 'authorized_scope_titles": []' in prompt
    assert len(prompt) <= 12_000
