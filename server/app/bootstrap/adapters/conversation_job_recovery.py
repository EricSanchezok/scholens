"""Atomic cross-module recovery for interrupted Conversation jobs."""

from __future__ import annotations

from app.modules.conversations.infrastructure.models import ConversationResponse
from app.modules.jobs.infrastructure.models import DurableJob
from app.shared.domain import FailureKind
from sqlalchemy.orm import Session


def fail_interrupted_conversation_response(
    db: Session,
    job: DurableJob,
) -> None:
    """Terminalize the response in the same transaction as its expired job."""
    response = db.get(ConversationResponse, job.id)
    if response is None or response.status != "running":
        return
    response.status = "failed"
    response.failure = {
        "code": "generation_interrupted",
        "kind": FailureKind.UNAVAILABLE.value,
        "retryable": True,
        "correlation_id": str(job.correlation_id),
    }
    response.turn.selected_response_id = response.id


__all__ = ["fail_interrupted_conversation_response"]
