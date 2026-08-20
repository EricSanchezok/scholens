"""Minimal composition root for the dedicated Conversation worker."""

from __future__ import annotations

from dataclasses import dataclass

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import (
    create_application_executor,
    create_citation_workflow,
    create_connector_tool_resolver,
    create_conversation_agent_runtime,
    create_conversation_chat,
    create_paper_ingestion_workflow,
    create_user_openalex,
    create_workspace_tooling,
)
from app.bootstrap.settings import AppSettings
from app.modules.conversations.application.chat import ConversationChat
from app.observability.diagnostics import create_diagnostic_snapshot_recorder
from app.shared.application import ApplicationExecutor, OperationContextFactory
from scholens_observability import (
    DiagnosticSnapshotRecorder,
    configure_logging,
    configure_telemetry,
)


@dataclass(frozen=True, slots=True)
class ConversationWorkerRuntime:
    settings: AppSettings
    executor: ApplicationExecutor[ApplicationCapabilities]
    operation_factory: OperationContextFactory
    chat: ConversationChat
    diagnostic_recorder: DiagnosticSnapshotRecorder


def create_conversation_worker_runtime() -> ConversationWorkerRuntime:
    """Compose only the capabilities required to finish a persisted response."""
    settings = AppSettings()
    configure_logging(
        service="scholens-conversation-worker",
        environment=settings.environment,
        release=settings.release_sha,
    )
    configure_telemetry(
        service="scholens-conversation-worker",
        environment=settings.environment,
        release=settings.release_sha,
        endpoint=settings.otel_exporter_otlp_endpoint,
    )
    diagnostic_recorder = create_diagnostic_snapshot_recorder(settings)
    operation_factory = OperationContextFactory()
    executor = create_application_executor(settings)
    connector_tools = create_connector_tool_resolver(
        executor=executor,
        settings=settings,
    )
    openalex = create_user_openalex(
        executor=executor,
        operation_factory=operation_factory,
    )
    ingestion = create_paper_ingestion_workflow(
        executor,
        operation_factory,
        openalex,
    )
    citations = create_citation_workflow(
        executor=executor,
        connector_tools=connector_tools,
        openalex=openalex,
        operation_factory=operation_factory,
    )
    catalog, dispatcher = create_workspace_tooling(
        executor=executor,
        ingestion=ingestion,
        citations=citations,
        settings=settings,
    )
    agent = create_conversation_agent_runtime(
        catalog=catalog,
        dispatcher=dispatcher,
        connector_tools=connector_tools,
        operation_factory=operation_factory,
    )
    return ConversationWorkerRuntime(
        settings=settings,
        executor=executor,
        operation_factory=operation_factory,
        chat=create_conversation_chat(
            executor,
            agent,
            operation_factory,
            diagnostic_recorder,
            settings.resolved_cache_url,
        ),
        diagnostic_recorder=diagnostic_recorder,
    )


__all__ = ["ConversationWorkerRuntime", "create_conversation_worker_runtime"]
