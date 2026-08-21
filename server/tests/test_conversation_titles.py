"""Initial Conversation title generation rules."""

from types import SimpleNamespace

import pytest

from app.llm.conversation_titles import (
    fallback_conversation_title,
    should_generate_initial_title,
)


@pytest.mark.parametrize(
    ("title_is_default", "roles", "expected"),
    [
        (True, ["user", "assistant"], True),
        (True, ["user", "user", "assistant"], True),
        (True, ["user"], False),
        (True, ["user", "assistant", "user", "assistant"], False),
        (False, ["user", "assistant"], False),
    ],
)
def test_initial_title_is_generated_after_only_the_first_assistant_reply(
    title_is_default: bool,
    roles: list[str],
    expected: bool,
) -> None:
    history = [SimpleNamespace(role=role, content=role) for role in roles]

    assert (
        should_generate_initial_title(
            title_is_default=title_is_default,
            chat_history=history,
        )
        is expected
    )


def test_fallback_title_is_cleaned_and_bounded() -> None:
    assert fallback_conversation_title("  ## Compare   RAG **memory**  ") == (
        "Compare RAG memory"
    )
    title = fallback_conversation_title("研" * 80)
    assert len(title) == 60
    assert title.endswith("…")
    assert fallback_conversation_title("  ###  ") == "Untitled question"
