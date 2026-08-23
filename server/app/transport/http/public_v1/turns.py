"""HTTP streaming endpoints for conversation turns and response variants."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from app.bootstrap.execution import (
    get_conversation_chat,
    get_operation_context_factory,
)
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.turns import (
    ConversationResponseCreateRequest,
    ConversationSubscriptionEventSchema,
    ConversationStreamEventSchema,
    ConversationTurnCreateRequest,
    ConversationTurnBranchCreateRequest,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationGenerationAccepted,
    ConversationGenerationCancellation,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.transport.client_ip import http_client_ip
from app.transport.http.observability import attach_operation_context
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

turn_router = APIRouter()


@dataclass(slots=True)
class _BufferedAssistantItem:
    item_id: str
    frames: list[str]
    deferred_frames: list[str]


class ConversationEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"

    def __init__(self, content: AsyncIterator[str], status_code: int = 200) -> None:
        super().__init__(
            content,
            status_code=status_code,
            media_type=self.media_type,
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Vary": "Accept",
            },
        )


def _stream_responses() -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": "Standard SSE stream of typed conversation events.",
            # FastAPI uses the additional response model to register every nested
            # event definition under OpenAPI components. The explicit content
            # entry below remains the canonical transport media type.
            "model": ConversationStreamEventSchema,
            "content": {
                "text/event-stream": {
                    "schema": {
                        "$ref": "#/components/schemas/ConversationStreamEventSchema"
                    }
                }
            },
        }
    }


def _subscription_responses() -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": "Replayable SSE subscription for an accepted response.",
            "model": ConversationSubscriptionEventSchema,
            "content": {
                "text/event-stream": {
                    "schema": {
                        "$ref": (
                            "#/components/schemas/ConversationSubscriptionEventSchema"
                        )
                    }
                }
            },
        }
    }


def _prefers_background(prefer: str | None) -> bool:
    return any(
        token.strip().casefold() == "respond-async"
        for token in (prefer or "").split(",")
    )


def _supports_provisional_items(accept: str | None) -> bool:
    for media_range in (accept or "").split(","):
        parts = [part.strip().casefold() for part in media_range.split(";")]
        if parts[0] == "text/event-stream" and "scholens-events=2" in parts[1:]:
            return True
    return False


def _conversation_event_payload(frame: str) -> dict[str, object] | None:
    data = "\n".join(
        line.removeprefix("data: ")
        for line in frame.splitlines()
        if line.startswith("data: ")
    )
    if not data:
        return None
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else None


async def _buffer_provisional_items_for_legacy_client(
    stream: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Hide provisional item semantics from clients using the v1 event protocol."""
    pending: _BufferedAssistantItem | None = None
    async for frame in stream:
        payload = _conversation_event_payload(frame)
        if payload is None:
            yield frame
            continue

        event_type = payload.get("type")
        item_id = payload.get("item_id")
        if pending is None:
            if event_type == "assistant_item_start" and isinstance(item_id, str):
                pending = _BufferedAssistantItem(item_id, [frame], [])
            elif event_type != "assistant_item_discard":
                yield frame
            continue

        if item_id == pending.item_id and event_type == "assistant_item_delta":
            pending.frames.append(frame)
            continue
        if event_type == "assistant_item_complete":
            item = payload.get("item")
            completed_item_id = item.get("id") if isinstance(item, dict) else None
            if completed_item_id == pending.item_id:
                for buffered in (*pending.frames, *pending.deferred_frames, frame):
                    yield buffered
                pending = None
                continue
        if item_id == pending.item_id and event_type == "assistant_item_discard":
            for deferred in pending.deferred_frames:
                yield deferred
            pending = None
            continue
        if event_type == "assistant_item_start" and isinstance(item_id, str):
            for deferred in pending.deferred_frames:
                yield deferred
            pending = _BufferedAssistantItem(item_id, [frame], [])
            continue
        if event_type in {"cancelled", "complete", "error"}:
            for deferred in (*pending.deferred_frames, frame):
                yield deferred
            pending = None
            continue
        pending.deferred_frames.append(frame)

    if pending is not None:
        for deferred in pending.deferred_frames:
            yield deferred


def _event_stream_response(
    stream: AsyncIterator[str], *, accept: str | None
) -> ConversationEventStreamResponse:
    if not _supports_provisional_items(accept):
        stream = _buffer_provisional_items_for_legacy_client(stream)
    return ConversationEventStreamResponse(stream)


def _conversation_operation(
    *,
    conversation_id: UUID,
    turn_id: UUID,
    request_operation: OperationContext,
    operation_factory: OperationContextFactory,
) -> OperationContext:
    if not isinstance(request_operation.origin, HttpOrigin):
        raise RuntimeError("conversation_http_origin_missing")
    return operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=request_operation.origin.request,
            conversation_id=conversation_id,
            turn_id=turn_id,
        ),
        credential=request_operation.credential,
    )


@turn_router.get("/capabilities")
def get_chat_capabilities(
    chat: ConversationChat = Depends(get_conversation_chat),
) -> dict[str, object]:
    return chat.capabilities()


@turn_router.post(
    "/{conversation_id}/turns",
    response_class=JSONResponse,
    response_model=ConversationGenerationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_stream_responses(),
)
async def create_conversation_turn(
    conversation_id: UUID,
    turn: ConversationTurnCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
    accept: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    if _prefers_background(prefer):
        accepted = await chat.accept(
            actor=current_user,
            operation=operation,
            conversation_id=conversation_id,
            request=turn,
            client_ip=http_client_ip(http_request),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted.model_dump(mode="json"),
            headers={"Preference-Applied": "respond-async"},
        )
    stream = await chat.stream(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        request=turn,
        client_ip=http_client_ip(http_request),
    )
    return _event_stream_response(stream, accept=accept)


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses",
    response_class=JSONResponse,
    response_model=ConversationGenerationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_stream_responses(),
)
async def retry_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    response: ConversationResponseCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
    accept: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    if _prefers_background(prefer):
        accepted = await chat.accept_retry(
            actor=current_user,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response.response_id,
            client_ip=http_client_ip(http_request),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted.model_dump(mode="json"),
            headers={"Preference-Applied": "respond-async"},
        )
    stream = await chat.retry(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response.response_id,
        client_ip=http_client_ip(http_request),
    )
    return _event_stream_response(stream, accept=accept)


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/branches",
    response_class=JSONResponse,
    response_model=ConversationGenerationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_stream_responses(),
)
async def branch_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    branch: ConversationTurnBranchCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
    accept: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=branch.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    if _prefers_background(prefer):
        accepted = await chat.accept_branch(
            actor=current_user,
            operation=operation,
            conversation_id=conversation_id,
            source_turn_id=turn_id,
            request=branch,
            client_ip=http_client_ip(http_request),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted.model_dump(mode="json"),
            headers={"Preference-Applied": "respond-async"},
        )
    stream = await chat.branch(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        source_turn_id=turn_id,
        request=branch,
        client_ip=http_client_ip(http_request),
    )
    return _event_stream_response(stream, accept=accept)


@turn_router.get(
    "/{conversation_id}/turns/{turn_id}/responses/{response_id}/events",
    response_class=ConversationEventStreamResponse,
    responses=_subscription_responses(),
)
async def subscribe_conversation_response(
    conversation_id: UUID,
    turn_id: UUID,
    response_id: UUID,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    accept: str | None = Header(default=None),
) -> ConversationEventStreamResponse:
    events = await chat.subscribe(
        actor=current_user,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
        last_event_id=last_event_id,
    )
    return _event_stream_response(events, accept=accept)


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses/{response_id}/cancel",
    response_model=ConversationGenerationCancellation,
)
async def cancel_conversation_response(
    conversation_id: UUID,
    turn_id: UUID,
    response_id: UUID,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
) -> ConversationGenerationCancellation:
    return await chat.cancel(
        actor=current_user,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
    )
