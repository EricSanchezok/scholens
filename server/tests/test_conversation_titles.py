"""Initial Conversation title generation rules."""

from app.llm.conversation_titles import (
    fallback_conversation_title,
)


def test_fallback_title_is_cleaned_and_bounded() -> None:
    assert fallback_conversation_title("  ## Compare   RAG **memory**  ") == (
        "Compare RAG memory"
    )
    title = fallback_conversation_title("研" * 80)
    assert len(title) == 60
    assert title.endswith("…")
    assert fallback_conversation_title("  ###  ") == "Untitled question"
