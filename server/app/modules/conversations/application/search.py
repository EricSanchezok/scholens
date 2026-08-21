"""Application boundary for private conversation search."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.search import (
    ConversationSearchPage,
    ConversationSearchPosition,
    ConversationSearchQuery,
    ConversationSearchRequest,
    ConversationSearchResponse,
)
from app.shared.application import Actor, SignedCursorCodec


class ConversationSearchCursorCodec(SignedCursorCodec):
    def __init__(self, secret: str) -> None:
        super().__init__(
            secret,
            revision="conversation-search-v1",
            error_code="conversation_search_cursor_expired",
        )

    def encode_position(
        self,
        *,
        fingerprint: str,
        position: ConversationSearchPosition,
    ) -> str:
        return self.encode_keyset(
            fingerprint=fingerprint,
            values=(
                repr(position.score),
                position.updated_at.isoformat(),
                str(position.conversation_id),
            ),
        )

    def decode_position(
        self,
        *,
        cursor: str,
        fingerprint: str,
    ) -> ConversationSearchPosition:
        values = self.decode_keyset(
            cursor=cursor,
            fingerprint=fingerprint,
            arity=3,
        )
        try:
            return ConversationSearchPosition(
                score=float(values[0]),
                updated_at=datetime.fromisoformat(values[1]),
                conversation_id=UUID(values[2]),
            )
        except (TypeError, ValueError):
            self._raise_invalid()


class ConversationSearchPort(Protocol):
    def search(
        self,
        *,
        actor: Actor,
        request: ConversationSearchQuery,
    ) -> ConversationSearchPage: ...


class SearchConversations:
    def __init__(
        self,
        search: ConversationSearchPort,
        cursors: ConversationSearchCursorCodec,
    ) -> None:
        self._search = search
        self._cursors = cursors

    def __call__(
        self,
        *,
        actor: Actor,
        request: ConversationSearchRequest,
    ) -> ConversationSearchResponse:
        normalized = request.model_copy(update={"query": request.query.strip()})
        fingerprint = json.dumps(
            {
                "actor_id": actor.id,
                "query": normalized.query,
                "limit": normalized.limit,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        position = (
            self._cursors.decode_position(
                cursor=normalized.cursor,
                fingerprint=fingerprint,
            )
            if normalized.cursor
            else None
        )
        page = self._search.search(
            actor=actor,
            request=ConversationSearchQuery(
                query=normalized.query,
                limit=normalized.limit,
                position=position,
            ),
        )
        next_cursor = (
            self._cursors.encode_position(
                fingerprint=fingerprint,
                position=page.next_position,
            )
            if page.next_position is not None
            else None
        )
        return ConversationSearchResponse(
            items=page.items,
            total=page.total,
            next_cursor=next_cursor,
        )
