"""In-memory HTTP dependencies do not wait for unrelated blocking work."""

import asyncio
from collections.abc import Callable

import anyio.to_thread
from app.bootstrap import execution
from app.transport.http.public_v1.billing import dependencies as billing
from fastapi import Depends, FastAPI
import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "state_name"),
    [
        (execution.get_application_executor, "application_executor"),
        (execution.get_integration_workflow, "integration_workflow"),
        (execution.get_operation_context_factory, "operation_context_factory"),
        (execution.get_conversation_chat, "conversation_chat"),
        (execution.get_citation_workflow, "citation_workflow"),
        (execution.get_paper_discovery_workflow, "paper_discovery_workflow"),
        (execution.get_tool_catalog, "tool_catalog"),
        (execution.get_tool_dispatcher, "tool_dispatcher"),
        (execution.get_onboarding_finisher, "onboarding_finisher"),
        (execution.get_stripe_webhook_processor, "stripe_webhook_processor"),
        (execution.get_paper_ingestion_workflow, "paper_ingestion_workflow"),
        (execution.get_research_generation_workflow, "research_generation_workflow"),
        (execution.get_translation_workflow, "translation_workflow"),
        (execution.get_zotero_workflow, "zotero_workflow"),
        (execution.get_job_completion_processor, "job_completion_processor"),
        (billing.get_billing_workflow, "billing_workflow"),
        (billing.get_billing_usage_workflow, "billing_usage_workflow"),
    ],
)
async def test_service_lookup_survives_busy_blocking_pool(
    dependency: Callable[..., object], state_name: str
) -> None:
    app = FastAPI()
    expected = object()
    setattr(app.state, state_name, expected)

    @app.get("/probe")
    async def probe(service: object = Depends(dependency)) -> dict[str, bool]:
        return {"same_instance": service is expected}

    # Reserve all blocking slots without sleeping, spawning real work, or
    # altering the global capacity. A pure lookup must still make progress.
    limiter = anyio.to_thread.current_default_thread_limiter()
    borrowers = [object() for _ in range(limiter.total_tokens)]
    for borrower in borrowers:
        limiter.acquire_on_behalf_of_nowait(borrower)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(client.get("/probe"), timeout=0.25)
        assert response.status_code == 200
        assert response.json() == {"same_instance": True}
    finally:
        for borrower in borrowers:
            limiter.release_on_behalf_of(borrower)
