"""Process lifecycle for authentication and durable-job dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from app.modules.identity.infrastructure.sanchezcloud_identity import auth_lifespan
from app.modules.jobs.infrastructure.dispatcher import run_job_dispatcher
from app.bootstrap.adapters.conversation_job_recovery import (
    fail_interrupted_conversation_response,
)
from app.observability.diagnostics import close_diagnostic_snapshot_recorder
from fastapi import FastAPI


@asynccontextmanager
async def app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    stop_dispatcher = asyncio.Event()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(auth_lifespan(application))
        mcp_manager = application.state.mcp_session_manager
        await stack.enter_async_context(mcp_manager.run())
        dispatcher = asyncio.create_task(
            run_job_dispatcher(
                stop_dispatcher,
                recover_conversation=fail_interrupted_conversation_response,
            ),
            name="jobs-outbox-dispatcher",
        )
        invitation_delivery = None
        supervisor = application.state.project_invitation_delivery_supervisor
        if supervisor is not None:
            invitation_delivery = asyncio.create_task(
                supervisor.run(stop_dispatcher),
                name="project-invitation-email-delivery",
            )
        try:
            yield
        finally:
            stop_dispatcher.set()
            await dispatcher
            if invitation_delivery is not None:
                await invitation_delivery
            close_diagnostic_snapshot_recorder(
                application.state.diagnostic_snapshot_recorder
            )
