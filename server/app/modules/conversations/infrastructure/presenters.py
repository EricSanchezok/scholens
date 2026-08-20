"""Map conversation ORM projections into application response contracts."""

from uuid import UUID

from app.modules.conversations.application.contracts.conversations import (
    ConversationResponseVariantResponse,
    ConversationTurnResponse,
)
from app.modules.conversations.infrastructure.models import (
    ConversationResponse,
    ConversationTurn,
)


def serialize_response(
    response: ConversationResponse,
) -> ConversationResponseVariantResponse:
    return ConversationResponseVariantResponse.model_validate(
        {
            "id": response.id,
            "variant_index": response.variant_index,
            "status": response.status,
            "content": response.content,
            "references": response.references,
            "artifacts": [
                item.citation.snapshot
                for item in response.research_items
                if item.citation is not None
            ]
            or None,
            "trace": response.trace,
            "duration_ms": response.duration_ms,
            "failure": response.failure,
        }
    )


def serialize_turns(
    turns: list[ConversationTurn],
    *,
    active_leaf_id: UUID | None,
    branch_groups: dict[UUID | None, list[UUID]],
) -> list[ConversationTurnResponse]:
    result: list[ConversationTurnResponse] = []
    for turn in turns:
        visible = (
            [
                response
                for response in turn.responses
                if response.status in {"running", "completed", "failed", "cancelled"}
            ]
            if turn.id == active_leaf_id
            else [
                response
                for response in turn.responses
                if response.id == turn.selected_response_id
            ]
        )
        responses = [serialize_response(response) for response in visible]
        siblings = branch_groups[turn.parent_turn_id]
        sibling_position = siblings.index(turn.id)
        result.append(
            ConversationTurnResponse.model_validate(
                {
                    "id": turn.id,
                    "parent_turn_id": turn.parent_turn_id,
                    "user_query": turn.user_query,
                    "contexts": turn.contexts or [],
                    "paper_context": turn.paper_context,
                    "reasoning_level": turn.reasoning_level,
                    "locale": turn.locale,
                    "time_zone": turn.time_zone,
                    "depth": turn.depth,
                    "branch": {
                        "index": sibling_position + 1,
                        "count": len(siblings),
                        "previous_turn_id": (
                            siblings[sibling_position - 1]
                            if sibling_position > 0
                            else None
                        ),
                        "next_turn_id": (
                            siblings[sibling_position + 1]
                            if sibling_position + 1 < len(siblings)
                            else None
                        ),
                    },
                    "selected_response_id": turn.selected_response_id,
                    "suggestions": turn.suggestions,
                    "responses": responses,
                }
            )
        )
    return result
