from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.bootstrap.adapters import conversation_worker
from app.shared.application import Actor, OperationContextFactory
from scholens_observability import ObservabilityContext, current_context


@pytest.mark.asyncio
async def test_generation_binds_worker_context_while_consuming_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = conversation_worker.ConversationGenerationTaskRequest(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        response_id=uuid4(),
        generation_kind="initial",
    )
    claimed = conversation_worker.ClaimedGeneration(
        actor=Actor(
            id=7,
            email="researcher@example.com",
            status="active",
            email_verified=True,
        ),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )
    previous_context = current_context()
    observed: list[ObservabilityContext] = []

    async def source() -> AsyncIterator[str]:
        observed.append(current_context())
        yield "event: complete\ndata: {}\n\n"

    class Chat:
        async def resume(self, **_kwargs: object) -> AsyncIterator[str]:
            return source()

    class EventStore:
        def __init__(self, _redis_url: str | None) -> None:
            pass

        async def publish(
            self,
            *,
            response_id: object,
            source: AsyncIterator[str],
        ) -> AsyncIterator[str]:
            del response_id
            async for frame in source:
                yield frame

    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            environment="production",
            release_sha="release-sha",
            resolved_cache_url="rediss://cache.example.com",
        ),
        operation_factory=OperationContextFactory(),
        chat=Chat(),
    )
    monkeypatch.setattr(conversation_worker, "_runtime", lambda: runtime)
    monkeypatch.setattr(conversation_worker, "ConversationEventStore", EventStore)

    await conversation_worker._run_generation(request, claimed)

    assert len(observed) == 1
    context = observed[0]
    assert context.service == "scholens-conversation-worker"
    assert context.environment == "production"
    assert context.release == "release-sha"
    assert context.correlation_id == str(claimed.correlation_id)
    assert context.causation_id == str(claimed.origin_operation_id)
    assert context.actor_id == str(claimed.actor.id)
    assert context.origin == "job"
    assert context.component == "conversation_generation"
    assert context.stage == "conversation_stream"
    assert context.conversation_id == str(request.conversation_id)
    assert context.turn_id == str(request.turn_id)
    assert context.job_id == str(request.response_id)
    assert current_context() == previous_context
