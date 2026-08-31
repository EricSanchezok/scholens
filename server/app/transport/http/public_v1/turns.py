"""HTTP streaming endpoints for conversation turns and response variants."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from app.bootstrap.execution import (
    get_conversation_chat,
    get_operation_context_factory,
)
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.turns import (
    ConversationCandidateSubscriptionEventSchema,
    ConversationResponseCreateRequest,
    ConversationStartRequest,
    ConversationStreamErrorEvent,
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
from app.shared.domain import FailureKind
from app.transport.client_ip import http_client_ip
from app.transport.http.observability import attach_operation_context
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

turn_router = APIRouter()

_CANDIDATE_EVENT_STREAM_MEDIA_TYPE = "application/vnd.scholens.conversation-events"


class ConversationEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


def _stream_responses(
    *,
    standard_schema: str,
    retain_legacy_json: bool,
) -> dict[int | str, dict[str, object]]:
    content = {
        "text/event-stream": {
            "schema": {"$ref": f"#/components/schemas/{standard_schema}"}
        },
        _CANDIDATE_EVENT_STREAM_MEDIA_TYPE: {
            "schema": {
                "$ref": (
                    "#/components/schemas/ConversationCandidateSubscriptionEventSchema"
                )
            }
        },
    }
    if retain_legacy_json:
        # This media type was published for the original three generation POSTs.
        # Runtime delivery remains SSE, but removing the documented shape would
        # break generated clients at the stable /api/v1 boundary.
        content["application/json"] = {
            "schema": {"$ref": "#/components/schemas/ConversationStreamEventSchema"}
        }
    return {
        200: {
            "description": (
                "A durable typed event stream. Request the Scholens candidate "
                "media type to include sanitized partial answer events."
            ),
            "content": content,
        },
        202: {
            "description": "Durable generation accepted for background delivery.",
            "model": ConversationGenerationAccepted,
        },
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


def _candidate_subscription_responses() -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": (
                "Replayable SSE subscription with sanitized answer candidates."
            ),
            "model": ConversationCandidateSubscriptionEventSchema,
            "content": {
                "text/event-stream": {
                    "schema": {
                        "$ref": (
                            "#/components/schemas/"
                            "ConversationCandidateSubscriptionEventSchema"
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


def _media_preference(
    accept: str | None,
    media_type: str,
) -> tuple[float, int] | None:
    target_type, _, target_subtype = media_type.casefold().partition("/")
    preferences: list[tuple[float, int]] = []
    for value in (accept or "").split(","):
        selected, *parameters = value.split(";")
        selected_type, separator, selected_subtype = (
            selected.strip().casefold().partition("/")
        )
        if not separator:
            continue
        if (selected_type, selected_subtype) == (target_type, target_subtype):
            specificity = 2
        elif (selected_type, selected_subtype) == (target_type, "*"):
            specificity = 1
        elif (selected_type, selected_subtype) == ("*", "*"):
            specificity = 0
        else:
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, raw_value = parameter.strip().partition("=")
            if separator and name.casefold() == "q":
                try:
                    quality = float(raw_value)
                except ValueError:
                    quality = 0.0
        preferences.append((quality if 0 <= quality <= 1 else 0.0, specificity))
    if not preferences:
        return None
    most_specific = max(specificity for _, specificity in preferences)
    return max(
        preference for preference in preferences if preference[1] == most_specific
    )


def _requests_candidate_stream(accept: str | None) -> bool:
    candidate_preference = _media_preference(
        accept,
        _CANDIDATE_EVENT_STREAM_MEDIA_TYPE,
    )
    if (
        candidate_preference is None
        or candidate_preference[0] <= 0
        or candidate_preference[1] != 2
    ):
        return False
    standard_preference = _media_preference(accept, "text/event-stream")
    return (
        standard_preference is None or candidate_preference[0] >= standard_preference[0]
    )


_EVENT_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Vary": "Accept",
    "X-Accel-Buffering": "no",
}


def _event_stream_response(
    events: AsyncIterator[str],
) -> ConversationEventStreamResponse:
    # Candidate events are selected through Accept, but the wire format must
    # remain standard SSE so browser-facing proxies recognize and flush it.
    return ConversationEventStreamResponse(
        events,
        headers=_EVENT_STREAM_HEADERS,
    )


def _legacy_compatible_frame(frame: str, *, response_id: UUID) -> str:
    if not any(line == "event: cancelled" for line in frame.splitlines()):
        return frame
    event_id = next(
        (line for line in frame.splitlines() if line.startswith("id: ")),
        None,
    )
    error = ConversationStreamErrorEvent(
        response_id=response_id,
        error={
            "code": "conversation_generation_cancelled",
            "kind": FailureKind.CONFLICT.value,
            "retryable": False,
        },
    )
    payload = json.dumps(
        error.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    error_frame = f"event: error\ndata: {payload}\n\n"
    return f"{event_id}\n{error_frame}" if event_id is not None else error_frame


async def _accepted_response(
    *,
    accepted: ConversationGenerationAccepted,
    chat: ConversationChat,
    actor: Actor,
    prefer: str | None,
    accept: str | None,
    legacy_stream: bool,
) -> Response:
    if _prefers_background(prefer):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted.model_dump(mode="json"),
            headers={"Preference-Applied": "respond-async"},
        )

    candidate_stream = _requests_candidate_stream(accept)

    async def events() -> AsyncIterator[str]:
        yield ": accepted\n\n"
        subscription = await chat.subscribe(
            actor=actor,
            conversation_id=accepted.conversation_id,
            turn_id=accepted.turn_id,
            response_id=accepted.response_id,
            last_event_id=None,
            include_assistant_candidates=candidate_stream,
        )
        async for frame in subscription:
            yield (
                _legacy_compatible_frame(frame, response_id=accepted.response_id)
                if legacy_stream and not candidate_stream
                else frame
            )

    return _event_stream_response(events())


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
    "/{conversation_id}/start",
    response_class=Response,
    response_model=ConversationSubscriptionEventSchema,
    status_code=status.HTTP_200_OK,
    responses=_stream_responses(
        standard_schema="ConversationSubscriptionEventSchema",
        retain_legacy_json=False,
    ),
)
async def start_conversation(
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
        accepted=accepted,
        chat=chat,
        actor=current_user,
        prefer=prefer,
        accept=http_request.headers.get("accept"),
        legacy_stream=False,
    )


@turn_router.post(
    "/{conversation_id}/turns",
    response_class=Response,
    response_model=ConversationStreamEventSchema,
    status_code=status.HTTP_200_OK,
    responses=_stream_responses(
        standard_schema="ConversationStreamEventSchema",
        retain_legacy_json=True,
    ),
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
        accepted=accepted,
        chat=chat,
        actor=current_user,
        prefer=prefer,
        accept=http_request.headers.get("accept"),
        legacy_stream=True,
    )


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses",
    response_class=Response,
    response_model=ConversationStreamEventSchema,
    status_code=status.HTTP_200_OK,
    responses=_stream_responses(
        standard_schema="ConversationStreamEventSchema",
        retain_legacy_json=True,
    ),
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
        accepted=accepted,
        chat=chat,
        actor=current_user,
        prefer=prefer,
        accept=http_request.headers.get("accept"),
        legacy_stream=True,
    )


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/branches",
    response_class=Response,
    response_model=ConversationStreamEventSchema,
    status_code=status.HTTP_200_OK,
    responses=_stream_responses(
        standard_schema="ConversationStreamEventSchema",
        retain_legacy_json=True,
    ),
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
        accepted=accepted,
        chat=chat,
        actor=current_user,
        prefer=prefer,
        accept=http_request.headers.get("accept"),
        legacy_stream=True,
    )


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
) -> ConversationEventStreamResponse:
    events = await chat.subscribe(
        actor=current_user,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
        last_event_id=last_event_id,
    )
    return _event_stream_response(events)


@turn_router.get(
    "/{conversation_id}/turns/{turn_id}/responses/{response_id}/events/candidates",
    response_class=ConversationEventStreamResponse,
    responses=_candidate_subscription_responses(),
)
async def subscribe_conversation_response_candidates(
    conversation_id: UUID,
    turn_id: UUID,
    response_id: UUID,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> ConversationEventStreamResponse:
    events = await chat.subscribe(
        actor=current_user,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
        last_event_id=last_event_id,
        include_assistant_candidates=True,
    )
    return _event_stream_response(events)


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
