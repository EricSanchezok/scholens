"""HTTP adapter for private conversation search."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.database.product_analytics import track_event
from app.modules.conversations.application.contracts.search import (
    ConversationSearchRequest,
    ConversationSearchResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user

conversation_search_router = APIRouter()


@conversation_search_router.post("", response_model=ConversationSearchResponse)
def search_conversations(
    request: ConversationSearchRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationSearchResponse:
    started_at = time.perf_counter()
    response = executor.query(
        lambda capabilities: capabilities.conversation_search(
            actor=current_user,
            request=request,
        )
    )
    track_event(
        "conversation_search",
        user_id=str(current_user.id),
        properties={
            "duration_ms": round((time.perf_counter() - started_at) * 1_000),
            "has_cursor": request.cursor is not None,
            "query_length": len(request.query),
            "total": response.total,
        },
    )
    return response
