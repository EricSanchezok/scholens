"""Conversation title generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from app.llm.backend import HistoryMessage, TextContent
from app.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)

_FALLBACK_TITLE_LIMIT = 60

_SYSTEM_PROMPT = """
You summarize conversations as concise, descriptive titles. Return plain text
only, using no more than five words, and reflect the conversation's main topic.
""".strip()

_USER_PROMPT = """
Generate a title for this conversation:

{chat_history}

Title:
""".strip()


def fallback_conversation_title(user_query: str) -> str:
    """Derive a stable, readable title when the optional LLM sidecar fails."""
    plain = re.sub(r"[`#>*_~\[\]{}()]", " ", user_query)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return "Untitled question"
    if len(plain) <= _FALLBACK_TITLE_LIMIT:
        return plain
    return f"{plain[: _FALLBACK_TITLE_LIMIT - 1].rstrip()}…"


class InitialConversationTitleGenerator(BaseLLMClient):
    def generate(
        self,
        chat_history: Sequence[HistoryMessage],
    ) -> str | None:
        if not chat_history:
            return None
        formatted_history = "\n".join(
            f"{message.role}: {message.content}" for message in chat_history[-4:]
        )
        response = self.generate_content(
            contents=[
                TextContent(
                    text=_USER_PROMPT.format(chat_history=formatted_history),
                )
            ],
            system_prompt=_SYSTEM_PROMPT,
        )
        if response and response.text:
            return response.text.strip()
        logger.error("conversation.title_generation.failed")
        return None


initial_conversation_title_generator = InitialConversationTitleGenerator()
