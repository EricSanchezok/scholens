"""Application executor construction and HTTP dependency."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.adapters.openalex import UserOpenAlex
from app.bootstrap.settings import AppSettings
from app.llm.conversation_agent import ScholensConversationAgent
from app.llm.follow_up_suggestions import FollowUpSuggestionGenerator
from app.database.database import SessionLocal
from app.modules.access_keys.application.contracts import AuthenticatedAccessKey
from app.modules.conversations.application.chat import ConversationChat
from app.modules.jobs.infrastructure.dispatcher_wakeup import JobDispatcherWakeup
from app.modules.identity.application.onboarding import FinishOnboarding
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.bootstrap.workflows.billing import BillingUsageWorkflow, BillingWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.bootstrap.workflows.pdf_postprocess import PdfPostprocessWorkflow
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.discovery import PaperDiscoveryWorkflow
from app.bootstrap.workflows.research_generation import ResearchGenerationWorkflow
from app.bootstrap.workflows.translation import TranslationWorkflow
from app.bootstrap.workflows.integrations import IntegrationWorkflow
from app.bootstrap.workflows.zotero import (
    ZoteroBackgroundWorkflow,
    ZoteroWorkflow,
)
from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.shared.application import (
    ApplicationExecutor,
    OperationContextFactory,
    SignedCursorCodec,
)
from app.shared.domain import FailureKind
from app.shared.infrastructure import SqlAlchemyApplicationExecutor, SystemClock
from app.tooling import ToolCatalog, ToolDispatcher
from app.tooling.paper_content_paging import PaperContentSnapshotCache
from app.transport.mcp.server import (
    AuthenticatedMcpApplication,
    build_mcp_transport,
)
from fastapi import Request
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

if TYPE_CHECKING:
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )
    from scholens_observability import DiagnosticSnapshotRecorder


def create_application_executor(
    settings: AppSettings,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        SessionLocal,
        lambda session: ApplicationCapabilities(session, settings),
    )


def create_connector_tool_resolver(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    settings: AppSettings,
) -> ConnectorToolResolver:
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )

    return ConnectorToolResolver(
        credential_loader=lambda actor: executor.query(
            lambda capabilities: (
                capabilities.integrations.enabled_connector_credentials(actor=actor)
            )
        ),
        settings=settings,
    )


def create_user_openalex(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
) -> UserOpenAlex:
    return UserOpenAlex(
        executor=executor,
        operation_factory=operation_factory,
    )


def create_integration_workflow(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    resolver: object,
    openalex: UserOpenAlex,
) -> IntegrationWorkflow:
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )

    assert isinstance(resolver, ConnectorToolResolver)
    return IntegrationWorkflow(
        executor=executor,
        resolver=resolver,
        openalex=openalex,
    )


def create_conversation_chat(
    executor: ApplicationExecutor[ApplicationCapabilities],
    runtime: ScholensConversationAgent,
    operation_factory: OperationContextFactory,
    diagnostic_recorder: DiagnosticSnapshotRecorder,
    event_store_url: str | None = None,
    dispatcher_wakeup: JobDispatcherWakeup | None = None,
) -> ConversationChat:
    from app.bootstrap.adapters.conversation_chat import (
        DefaultConversationChatGateway,
    )

    return ConversationChat(
        DefaultConversationChatGateway(
            executor,
            runtime,
            operation_factory,
            diagnostic_recorder,
            FollowUpSuggestionGenerator(),
            event_store_url,
            dispatcher_wakeup,
        )
    )


def create_citation_workflow(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    connector_tools: object,
    openalex: UserOpenAlex,
    operation_factory: OperationContextFactory,
) -> CitationWorkflow:
    from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )

    assert isinstance(connector_tools, ConnectorToolResolver)
    return CitationWorkflow(
        executor=executor,
        provider=CitationMetadataProvider(connector_tools, openalex),
        operation_factory=operation_factory,
    )


def create_paper_discovery_workflow(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    settings: AppSettings,
    operation_factory: OperationContextFactory,
    openalex: UserOpenAlex,
) -> PaperDiscoveryWorkflow:
    from app.bootstrap.container import build_external_paper_discovery

    return PaperDiscoveryWorkflow(
        executor=executor,
        external=build_external_paper_discovery(
            cursor_secret=settings.paper_search_cursor_secret,
            catalog=openalex,
        ),
        operation_factory=operation_factory,
    )


def create_workspace_tooling(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    ingestion: PaperIngestionWorkflow,
    citations: CitationWorkflow,
    settings: AppSettings,
    paper_content_snapshot_cache: PaperContentSnapshotCache | None = None,
) -> tuple[
    ToolCatalog[ApplicationCapabilities],
    ToolDispatcher[ApplicationCapabilities],
]:
    from app.tooling.workspace import build_workspace_tool_catalog

    catalog = build_workspace_tool_catalog(
        executor=executor,
        ingestion=ingestion,
        citations=citations,
        web_base_url=settings.client_domain,
        cursor_secret=settings.paper_search_cursor_secret,
        paper_content_snapshot_cache=paper_content_snapshot_cache,
    )
    return catalog, ToolDispatcher(catalog=catalog, executor=executor)


def create_conversation_agent_runtime(
    *,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
    connector_tools: object,
    operation_factory: OperationContextFactory,
) -> ScholensConversationAgent:
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )

    assert isinstance(connector_tools, ConnectorToolResolver)
    return ScholensConversationAgent(
        catalog=catalog,
        dispatcher=dispatcher,
        connector_tools=connector_tools,
        operation_factory=operation_factory,
        clock=SystemClock(),
    )


def create_mcp_transport(
    *,
    settings: AppSettings,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
    diagnostic_recorder: DiagnosticSnapshotRecorder,
) -> tuple[StreamableHTTPSessionManager, AuthenticatedMcpApplication]:
    async def authenticate(token: str) -> AuthenticatedAccessKey:
        return await asyncio.to_thread(
            executor.command,
            lambda capabilities: capabilities.access_keys.authenticate(token),
        )

    public_url = urlsplit(settings.client_domain)
    public_host = public_url.netloc
    allowed_hosts = [public_host]
    allowed_origins = [settings.client_domain.rstrip("/")]
    if settings.environment.casefold() != "production":
        allowed_hosts.extend(["localhost:*", "127.0.0.1:*", "testserver"])
        allowed_origins.extend(["http://localhost:*", "http://127.0.0.1:*"])
    return build_mcp_transport(
        catalog=catalog,
        dispatcher=dispatcher,
        executor=executor,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
        authenticate=authenticate,
        operation_factory=operation_factory,
        diagnostic_recorder=diagnostic_recorder,
    )


def create_onboarding_finisher() -> FinishOnboarding:
    from app.bootstrap.container import build_finish_onboarding

    return build_finish_onboarding()


def create_billing_workflow(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
) -> BillingWorkflow:
    from app.modules.billing.infrastructure.application_gateway import (
        PostHogBillingEvents,
        StripePaymentProvider,
    )

    return BillingWorkflow(
        executor=executor,
        payments=StripePaymentProvider(),
        events=PostHogBillingEvents(),
        operation_factory=operation_factory,
    )


def create_billing_usage_workflow(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
) -> BillingUsageWorkflow:
    return BillingUsageWorkflow(executor=executor)


def create_stripe_webhook_processor(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
) -> ProcessStripeWebhook:
    from app.bootstrap.adapters.stripe_webhook import StripeWebhookWorkflow
    from app.database.database import engine
    from app.modules.billing.infrastructure.application_gateway import (
        PostHogBillingEvents,
    )
    from app.modules.billing.infrastructure.config import STRIPE_WEBHOOK_SECRET

    return StripeWebhookWorkflow(
        executor=executor,
        session_factory=SessionLocal,
        engine=engine,
        operation_factory=operation_factory,
        events=PostHogBillingEvents(),
        webhook_secret=STRIPE_WEBHOOK_SECRET,
    )


def create_paper_ingestion_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
    openalex: UserOpenAlex,
) -> PaperIngestionWorkflow:
    from app.bootstrap.container import (
        build_paper_source_resolver,
        build_pdf_url_source,
    )
    from app.modules.jobs.infrastructure.client import jobs_client

    return PaperIngestionWorkflow(
        executor=executor,
        url_source=build_pdf_url_source(),
        source_resolver=build_paper_source_resolver(openalex=openalex),
        operation_factory=operation_factory,
        jobs=jobs_client,
    )


def create_research_generation_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
) -> ResearchGenerationWorkflow:
    from app.bootstrap.container import build_generation_capacity

    return ResearchGenerationWorkflow(
        executor=executor,
        capacity=build_generation_capacity(),
        operation_factory=operation_factory,
    )


def create_translation_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
    settings: AppSettings,
    diagnostic_recorder: DiagnosticSnapshotRecorder,
) -> TranslationWorkflow:
    from app.database.database import SessionLocal
    from app.modules.translations.infrastructure.capacity import (
        RedisTranslationCapacity,
    )
    from app.modules.translations.infrastructure.provider import (
        LLMTranslationStreamProvider,
    )
    from app.modules.translations.infrastructure.result_store import (
        SqlTranslationResultStore,
    )
    from app.modules.translations.infrastructure.singleflight import (
        RedisTranslationSingleFlight,
    )

    return TranslationWorkflow(
        executor=executor,
        result_store=SqlTranslationResultStore(SessionLocal),
        singleflight=RedisTranslationSingleFlight(settings.resolved_cache_url),
        provider=LLMTranslationStreamProvider(),
        capacity=RedisTranslationCapacity(
            redis_url=settings.resolved_cache_url,
            environment=settings.environment,
        ),
        diagnostic_recorder=diagnostic_recorder,
    )


def create_zotero_workflow(
    executor: ApplicationExecutor[ApplicationCapabilities],
    operation_factory: OperationContextFactory,
    settings: AppSettings,
) -> ZoteroWorkflow:
    from app.bootstrap.adapters.zotero_operations import DefaultZoteroOperations

    return ZoteroWorkflow(
        executor=executor,
        operations=DefaultZoteroOperations(),
        operation_factory=operation_factory,
        cursors=SignedCursorCodec(
            settings.paper_search_cursor_secret,
            revision="zotero-library-v1",
            error_code="zotero_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
    )


def create_job_completion_processor(
    executor: ApplicationExecutor[ApplicationCapabilities],
    connector_tools: object,
    operation_factory: OperationContextFactory,
    openalex: UserOpenAlex,
) -> JobCompletionProcessor:
    from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
    from app.bootstrap.adapters.document_job_callbacks import (
        SqlAlchemyPdfPostprocessReader,
    )
    from app.bootstrap.adapters.zotero_operations import DefaultZoteroOperations
    from app.modules.integrations.connectors.infrastructure.mcp import (
        ConnectorToolResolver,
    )

    assert isinstance(connector_tools, ConnectorToolResolver)
    return JobCompletionProcessor(
        session_factory=SessionLocal,
        executor=executor,
        operation_factory=operation_factory,
        pdf_postprocess=PdfPostprocessWorkflow(
            executor=executor,
            reader=SqlAlchemyPdfPostprocessReader(SessionLocal),
            provider=CitationMetadataProvider(connector_tools, openalex),
            operation_factory=operation_factory,
        ),
        zotero_background=ZoteroBackgroundWorkflow(
            executor=executor,
            operations=DefaultZoteroOperations(),
            operation_factory=operation_factory,
        ),
    )


def get_application_executor(
    request: Request,
) -> ApplicationExecutor[ApplicationCapabilities]:
    return cast(
        ApplicationExecutor[ApplicationCapabilities],
        request.app.state.application_executor,
    )


def get_integration_workflow(request: Request) -> IntegrationWorkflow:
    return cast(IntegrationWorkflow, request.app.state.integration_workflow)


def get_operation_context_factory(request: Request) -> OperationContextFactory:
    return cast(
        OperationContextFactory,
        request.app.state.operation_context_factory,
    )


def get_conversation_chat(request: Request) -> ConversationChat:
    return cast(ConversationChat, request.app.state.conversation_chat)


def get_citation_workflow(request: Request) -> CitationWorkflow:
    return cast(CitationWorkflow, request.app.state.citation_workflow)


def get_paper_discovery_workflow(request: Request) -> PaperDiscoveryWorkflow:
    return cast(
        PaperDiscoveryWorkflow,
        request.app.state.paper_discovery_workflow,
    )


def get_tool_catalog(
    request: Request,
) -> ToolCatalog[ApplicationCapabilities]:
    return cast(
        ToolCatalog[ApplicationCapabilities],
        request.app.state.tool_catalog,
    )


def get_tool_dispatcher(
    request: Request,
) -> ToolDispatcher[ApplicationCapabilities]:
    return cast(
        ToolDispatcher[ApplicationCapabilities],
        request.app.state.tool_dispatcher,
    )


def get_onboarding_finisher(request: Request) -> FinishOnboarding:
    return cast(FinishOnboarding, request.app.state.onboarding_finisher)


def get_stripe_webhook_processor(request: Request) -> ProcessStripeWebhook:
    return cast(ProcessStripeWebhook, request.app.state.stripe_webhook_processor)


def get_paper_ingestion_workflow(request: Request) -> PaperIngestionWorkflow:
    return cast(PaperIngestionWorkflow, request.app.state.paper_ingestion_workflow)


def get_research_generation_workflow(
    request: Request,
) -> ResearchGenerationWorkflow:
    return cast(
        ResearchGenerationWorkflow,
        request.app.state.research_generation_workflow,
    )


def get_translation_workflow(request: Request) -> TranslationWorkflow:
    return cast(TranslationWorkflow, request.app.state.translation_workflow)


def get_zotero_workflow(request: Request) -> ZoteroWorkflow:
    return cast(ZoteroWorkflow, request.app.state.zotero_workflow)


def get_job_completion_processor(request: Request) -> JobCompletionProcessor:
    return cast(
        JobCompletionProcessor,
        request.app.state.job_completion_processor,
    )
