"""Research-agent style replayable conversation SSE transport."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.bootstrap.execution import get_conversation_chat, get_operation_context_factory
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.conversations import (
    ConversationGenerationAccepted,
    ConversationGenerationCancellation,
)
from app.modules.conversations.application.contracts.stream_v2 import (
    ConversationStreamV2Accepted,
    ConversationStreamV2Event,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationResponseCreateRequest,
    ConversationStartRequest,
    ConversationTurnBranchCreateRequest,
    ConversationTurnCreateRequest,
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

v2_turn_router = APIRouter()


class ConversationV2EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


_EVENT_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Vary": "Accept",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}


def _stream_response(events: AsyncIterator[str]) -> ConversationV2EventStreamResponse:
    return ConversationV2EventStreamResponse(events, headers=_EVENT_STREAM_HEADERS)


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


def _json_data(frame: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    event = next(
        (
            line.removeprefix("event: ")
            for line in frame.splitlines()
            if line.startswith("event: ")
        ),
        None,
    )
    event_id = next(
        (
            line.removeprefix("id: ")
            for line in frame.splitlines()
            if line.startswith("id: ")
        ),
        None,
    )
    data = "\n".join(
        line.removeprefix("data: ")
        for line in frame.splitlines()
        if line.startswith("data: ")
    )
    if not data:
        return event, None, event_id
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return event, None, event_id
    return event, value if isinstance(value, dict) else None, event_id


def _stable_seq(event_id: str | None, fallback: int) -> int:
    if event_id:
        try:
            milliseconds, offset = event_id.split("-", 1)
            value = (int(milliseconds) << 20) + int(offset)
            if value > 0:
                return value
        except (ValueError, TypeError):
            pass
    return max(1, fallback)


def _safe_activity(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in (
            "id",
            "sequence",
            "category",
            "state",
            "subject",
            "connector_name",
            "source_count",
            "artifact_count",
        )
        if key in value and value[key] is not None
    }


def _upgrade_frame(
    frame: str,
    *,
    response_id: UUID,
    fallback_seq: int,
) -> str:
    event_type, payload, event_id = _json_data(frame)
    if event_type is None or payload is None:
        return frame
    seq = _stable_seq(event_id, fallback_seq)
    data: dict[str, Any]
    event: str
    if event_type == "start":
        event, data = "turn.started", payload
    elif event_type == "phase":
        event, data = (
            "phase.updated",
            {
                "phase": payload.get("phase", "thinking"),
                "elapsed_ms": payload.get("elapsed_ms", 0),
            },
        )
    elif event_type == "activity":
        activity = _safe_activity(payload.get("activity"))
        event, data = (
            "message.part.updated",
            {
                "part_id": activity.get("id", f"activity:{seq}"),
                "part_kind": "activity",
                "version": seq,
                "state": activity.get("state", "running"),
                "presentation": activity,
            },
        )
    elif event_type in {"assistant_item_start", "assistant_candidate_start"}:
        event, data = (
            "message.part.updated",
            {
                "part_id": payload.get("item_id", f"part:{seq}"),
                "part_kind": "progress"
                if event_type == "assistant_item_start"
                else "candidate",
                "version": seq,
                "state": "running",
                "sequence": payload.get("sequence", 1),
            },
        )
    elif event_type in {"assistant_item_delta", "assistant_candidate_delta"}:
        event, data = (
            "message.part.delta",
            {
                "part_id": payload.get("item_id", f"part:{seq}"),
                "part_kind": "progress"
                if event_type == "assistant_item_delta"
                else "candidate",
                "version": seq,
                "delta": payload.get("delta", ""),
            },
        )
    elif event_type == "assistant_candidate_reset":
        event, data = (
            "message.part.reset",
            {
                "part_id": payload.get("item_id", f"part:{seq}"),
                "version": seq,
                "reason": "candidate_repaired",
            },
        )
    elif event_type == "assistant_item_complete":
        item = payload.get("item")
        item_dict = item if isinstance(item, dict) else {}
        event, data = (
            "message.part.completed",
            {
                "part_id": item_dict.get("id", f"part:{seq}"),
                "part_kind": "final"
                if item_dict.get("phase") == "final"
                else "progress",
                "version": seq,
                "state": "completed",
                "snapshot": item_dict,
            },
        )
    elif event_type == "references":
        event, data = "references.ready", payload
    elif event_type == "response_ready":
        event, data = "response.ready", payload
    elif event_type == "suggestions":
        event, data = "suggestions.ready", payload
    elif event_type == "complete":
        event, data = "turn.completed", payload
    elif event_type == "cancelled":
        event, data = "turn.canceled", payload
    elif event_type == "error":
        event, data = "turn.failed", payload
    else:
        return frame
    envelope = ConversationStreamV2Event(
        event=event,
        response_id=response_id,
        seq=seq,
        emitted_at=datetime.now(timezone.utc),
        data=data,
    )
    serialized = json.dumps(
        envelope.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}event: {event}\ndata: {serialized}\n\n"


async def _upgraded_events(
    source: AsyncIterator[str], *, response_id: UUID
) -> AsyncIterator[str]:
    fallback_seq = 1
    async for frame in source:
        upgraded = _upgrade_frame(
            frame,
            response_id=response_id,
            fallback_seq=fallback_seq,
        )
        fallback_seq += 1
        yield upgraded


async def _accepted_response(
    *,
    accepted: ConversationGenerationAccepted,
    chat: ConversationChat,
    actor: Actor,
    prefer: str | None,
) -> Response:
    if prefer and any(
        token.strip().casefold() == "respond-async" for token in prefer.split(",")
    ):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=ConversationStreamV2Accepted.model_validate(
                accepted.model_dump()
            ).model_dump(mode="json"),
            headers={"Preference-Applied": "respond-async"},
        )

    async def events() -> AsyncIterator[str]:
        yield ": accepted\n\n"
        subscription = await chat.subscribe(
            actor=actor,
            conversation_id=accepted.conversation_id,
            turn_id=accepted.turn_id,
            response_id=accepted.response_id,
            last_event_id=None,
            include_assistant_candidates=True,
            include_phase_events=True,
        )
        async for frame in _upgraded_events(
            subscription, response_id=accepted.response_id
        ):
            yield frame

    return _stream_response(events())


def _responses() -> dict[int | str, dict[str, Any]]:
    return {
        200: {
            "description": "Unified replayable v2 conversation SSE stream.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/ConversationStreamV2Event"}
                }
            },
        },
        202: {
            "description": "Durable generation accepted for background delivery.",
            "model": ConversationStreamV2Accepted,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ConversationStreamV2Accepted"
                    }
                }
            },
        },
    }


@v2_turn_router.post(
    "/{conversation_id}/start",
    response_class=Response,
    responses=_responses(),
)
async def start_conversation_v2(
    conversation_id: UUID,
    start: ConversationStartRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=start.turn.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    accepted = await chat.accept_start(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        conversation=start.conversation,
        request=start.turn,
        client_ip=http_client_ip(http_request),
    )
    return await _accepted_response(
        accepted=accepted, chat=chat, actor=current_user, prefer=prefer
    )


@v2_turn_router.post(
    "/{conversation_id}/turns",
    response_class=Response,
    responses=_responses(),
)
async def create_conversation_turn_v2(
    conversation_id: UUID,
    turn: ConversationTurnCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    accepted = await chat.accept(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        request=turn,
        client_ip=http_client_ip(http_request),
    )
    return await _accepted_response(
        accepted=accepted, chat=chat, actor=current_user, prefer=prefer
    )


@v2_turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses",
    response_class=Response,
    responses=_responses(),
)
async def retry_conversation_turn_v2(
    conversation_id: UUID,
    turn_id: UUID,
    response: ConversationResponseCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    accepted = await chat.accept_retry(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response.response_id,
        client_ip=http_client_ip(http_request),
    )
    return await _accepted_response(
        accepted=accepted, chat=chat, actor=current_user, prefer=prefer
    )


@v2_turn_router.post(
    "/{conversation_id}/turns/{turn_id}/branches",
    response_class=Response,
    responses=_responses(),
)
async def branch_conversation_turn_v2(
    conversation_id: UUID,
    turn_id: UUID,
    branch: ConversationTurnBranchCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    prefer: str | None = Header(default=None),
) -> Response:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=branch.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    accepted = await chat.accept_branch(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        source_turn_id=turn_id,
        request=branch,
        client_ip=http_client_ip(http_request),
    )
    return await _accepted_response(
        accepted=accepted, chat=chat, actor=current_user, prefer=prefer
    )


@v2_turn_router.get(
    "/{conversation_id}/turns/{turn_id}/responses/{response_id}/events",
    response_class=ConversationV2EventStreamResponse,
    responses={
        200: {
            "description": "Replayable unified v2 conversation SSE stream.",
            "model": ConversationStreamV2Event,
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/ConversationStreamV2Event"}
                }
            },
        }
    },
)
async def subscribe_conversation_response_v2(
    conversation_id: UUID,
    turn_id: UUID,
    response_id: UUID,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> ConversationV2EventStreamResponse:
    events = await chat.subscribe(
        actor=current_user,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
        last_event_id=last_event_id,
        include_assistant_candidates=True,
        include_phase_events=True,
    )
    return _stream_response(_upgraded_events(events, response_id=response_id))


@v2_turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses/{response_id}/cancel"
)
async def cancel_conversation_response_v2(
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


__all__ = ["v2_turn_router"]
