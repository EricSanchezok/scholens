"""FastAPI composition root.

Routers are assembled only here so versioning and trust boundaries cannot be
silently changed by individual business modules.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from app.transport.http.public_v1.auth import (
    admin_router,
    topics_router,
)
from app.transport.http.public_v1.access_keys import access_keys_router
from app.transport.http.public_v1.integrations import integrations_router
from app.transport.http.public_v1.conversations import conversation_router
from app.transport.http.public_v1.conversation_search import (
    conversation_search_router,
)
from app.transport.http.public_v1.document_uploads import document_upload_router
from app.transport.http.public_v1.documents import (
    document_router,
    library_router,
    public_document_router,
)
from app.transport.http.internal_v1.jobs_callbacks import (
    webhook_router as jobs_callback_router,
)
from app.transport.http.public_v1.library_tags import library_tags_router
from app.transport.http.public_v1.turns import turn_router
from app.transport.http.public_v1.discovery import (
    author_discovery_router,
    paper_search_router,
)
from app.transport.http.public_v1.projects.documents import (
    library_project_papers_router,
    paper_projects_router,
    project_papers_router,
)
from app.transport.http.public_v1.projects.projects import projects_router
from app.transport.http.public_v1.projects.invitations import (
    router as projects_invitation_router,
)
from app.transport.http.public_v1.research import (
    document_research_router,
    project_research_router,
    research_router,
)
from app.transport.http.public_v1.research_generation import (
    document_generation_router,
    jobs_router,
    project_generation_router,
)
from app.transport.http.public_v1.paper_search import search_router
from app.transport.http.public_v1.research_search import research_search_router
from app.transport.http.public_v1.billing import usage_router
from app.transport.http.public_v1.zotero import zotero_oauth_router, zotero_router
from app.transport.http.public_v1.translations import (
    paper_translations_router,
    translation_preferences_router,
)
from app.transport.http.public_v1.paper_list_preferences import (
    paper_list_preferences_router,
)
from app.transport.http.public_v1.reflows import paper_reflows_router
from app.transport.http.public_v1.reading_activity import (
    reading_activity_me_router,
    reading_activity_papers_router,
    reading_activity_preferences_router,
    reading_activity_projects_router,
    reading_activity_sessions_router,
)
from app.modules.identity.infrastructure.sanchezcloud_identity import (
    sanchezcloud_identity_router,
    identity_user_router,
)
from app.observability import configure_application_observability
from app.observability.diagnostics import create_diagnostic_snapshot_recorder
from app.bootstrap.lifespan import app_lifespan
from app.bootstrap.execution import (
    create_application_executor,
    create_billing_usage_workflow,
    create_connector_tool_resolver,
    create_integration_workflow,
    create_conversation_agent_runtime,
    create_conversation_chat,
    create_citation_workflow,
    create_job_completion_processor,
    create_mcp_transport,
    create_onboarding_finisher,
    create_paper_discovery_workflow,
    create_paper_ingestion_workflow,
    create_research_generation_workflow,
    create_translation_workflow,
    create_user_openalex,
    create_workspace_tooling,
    create_zotero_workflow,
)
from app.bootstrap.settings import (
    INTERNAL_API_PREFIX,
    PUBLIC_API_PREFIX,
    AppSettings,
)
from app.database.admin import setup_admin
from app.database.database import SessionLocal
from app.modules.notifications.infrastructure import AliyunTransactionalEmailSender
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.modules.projects.infrastructure.invitation_delivery import (
    ProjectInvitationDeliverySupervisor,
)
from app.shared.domain import AppError
from app.shared.application import OperationContextFactory
from app.tooling.paper_content_paging import PaperContentSnapshotCache
from app.shared.infrastructure.email_settings import email_settings
from app.modules.jobs.infrastructure.dispatcher_wakeup import JobDispatcherWakeup
from app.transport.http.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.transport.http.error_boundary import UnhandledErrorMiddleware
from app.transport.http.observability import RequestObservabilityMiddleware
from app.transport.http.public_v1.identity import router as identity_router
from app.transport.http.public_v1.onboarding import onboarding_router
from app.transport.http.public_v2.turns import v2_turn_router
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Route

logger = logging.getLogger(__name__)


def _public_router() -> APIRouter:
    router = APIRouter()
    router.include_router(identity_router)
    router.include_router(sanchezcloud_identity_router, prefix="/auth", tags=["auth"])
    router.include_router(identity_user_router, prefix="/me", tags=["user"])
    router.include_router(topics_router, prefix="/discovery")
    router.include_router(admin_router, prefix="/admin")
    router.include_router(
        zotero_oauth_router,
        prefix="/integrations/zotero/oauth",
        tags=["zotero"],
    )
    # Static chat capability routes must precede the UUID conversation route.
    router.include_router(turn_router, prefix="/conversations")
    router.include_router(conversation_router, prefix="/conversations")
    router.include_router(library_router, prefix="/library")
    router.include_router(library_project_papers_router, prefix="/library")
    router.include_router(library_tags_router, prefix="/library")
    router.include_router(document_router, prefix="/papers")
    router.include_router(reading_activity_papers_router, prefix="/papers")
    router.include_router(paper_translations_router, prefix="/papers")
    router.include_router(paper_reflows_router, prefix="/papers")
    router.include_router(paper_projects_router, prefix="/papers")
    router.include_router(public_document_router, prefix="/shares")
    router.include_router(projects_router, prefix="/projects")
    router.include_router(reading_activity_projects_router, prefix="/projects")
    router.include_router(project_papers_router, prefix="/projects")
    router.include_router(projects_invitation_router)
    router.include_router(paper_search_router, prefix="/discovery/papers")
    router.include_router(author_discovery_router, prefix="/discovery")
    router.include_router(search_router, prefix="/search/papers")
    router.include_router(
        conversation_search_router,
        prefix="/search/conversations",
    )
    router.include_router(research_search_router, prefix="/search/research")
    router.include_router(document_upload_router, prefix="/paper-ingestions")
    router.include_router(document_research_router, prefix="/papers")
    router.include_router(project_research_router, prefix="/projects")
    router.include_router(research_router)
    router.include_router(document_generation_router, prefix="/papers")
    router.include_router(project_generation_router, prefix="/projects")
    router.include_router(jobs_router, prefix="/jobs")
    router.include_router(usage_router, prefix="/billing")
    router.include_router(onboarding_router, prefix="/me/onboarding")
    router.include_router(translation_preferences_router, prefix="/me")
    router.include_router(paper_list_preferences_router, prefix="/me")
    router.include_router(reading_activity_preferences_router, prefix="/me")
    router.include_router(reading_activity_me_router, prefix="/me")
    router.include_router(reading_activity_sessions_router, prefix="/reading-sessions")
    router.include_router(
        access_keys_router,
        prefix="/me/access-keys",
        tags=["access-keys"],
    )
    router.include_router(integrations_router, prefix="/me/integrations")
    router.include_router(zotero_router, prefix="/integrations/zotero")
    return router


def create_app(settings: AppSettings | None = None) -> FastAPI:
    runtime_settings = settings or AppSettings()
    application = FastAPI(
        title="Scholens",
        description="Scholens public application API.",
        version="1.0.0",
        lifespan=app_lifespan,
        exception_handlers={
            AppError: app_error_handler,
            RequestValidationError: validation_error_handler,
            StarletteHTTPException: http_error_handler,
            Exception: unhandled_error_handler,
        },
    )
    application.state.settings = runtime_settings
    email_settings.validate_configuration(
        required=runtime_settings.environment.casefold() == "production"
    )
    application.state.project_invitation_delivery_supervisor = None
    if email_settings.configured:
        application.state.project_invitation_delivery_supervisor = ProjectInvitationDeliverySupervisor(
            session_factory=SessionLocal,
            sender=AliyunTransactionalEmailSender(
                access_key_id=email_settings.scholens_aliyun_dm_access_key_id,
                access_key_secret=email_settings.scholens_aliyun_dm_access_key_secret,
                account_name=email_settings.scholens_aliyun_dm_account_name,
                from_alias=email_settings.scholens_aliyun_dm_from_alias,
                reply_to_address=email_settings.scholens_aliyun_dm_reply_to_address,
            ),
            token_codec=ProjectInvitationTokenCodec(
                runtime_settings.project_invitation_token_secret
            ),
            client_domain=runtime_settings.client_domain,
            idle_seconds=runtime_settings.project_invitation_delivery_interval_seconds,
            delivery_lease=timedelta(
                seconds=runtime_settings.project_invitation_delivery_lease_seconds
            ),
        )
    application.state.diagnostic_snapshot_recorder = (
        create_diagnostic_snapshot_recorder(runtime_settings)
    )
    operation_context_factory = OperationContextFactory()
    application.state.operation_context_factory = operation_context_factory
    application.state.job_dispatcher_wakeup = JobDispatcherWakeup()
    executor = create_application_executor(runtime_settings)
    application.state.application_executor = executor
    connector_tool_resolver = create_connector_tool_resolver(
        executor=executor,
        settings=runtime_settings,
    )
    user_openalex = create_user_openalex(
        executor=executor,
        operation_factory=operation_context_factory,
    )
    application.state.connector_tool_resolver = connector_tool_resolver
    application.state.integration_workflow = create_integration_workflow(
        executor=executor,
        resolver=connector_tool_resolver,
        openalex=user_openalex,
    )
    ingestion_workflow = create_paper_ingestion_workflow(
        executor,
        operation_context_factory,
        user_openalex,
    )
    citation_workflow = create_citation_workflow(
        executor=executor,
        connector_tools=connector_tool_resolver,
        operation_factory=operation_context_factory,
        openalex=user_openalex,
    )
    paper_content_snapshot_cache = PaperContentSnapshotCache()
    tool_catalog, tool_dispatcher = create_workspace_tooling(
        executor=executor,
        ingestion=ingestion_workflow,
        citations=citation_workflow,
        settings=runtime_settings,
        paper_content_snapshot_cache=paper_content_snapshot_cache,
    )
    conversation_runtime = create_conversation_agent_runtime(
        catalog=tool_catalog,
        dispatcher=tool_dispatcher,
        connector_tools=connector_tool_resolver,
        operation_factory=operation_context_factory,
    )
    application.state.tool_catalog = tool_catalog
    application.state.tool_dispatcher = tool_dispatcher
    application.state.conversation_agent_runtime = conversation_runtime
    mcp_manager, mcp_application = create_mcp_transport(
        settings=runtime_settings,
        catalog=tool_catalog,
        dispatcher=tool_dispatcher,
        executor=executor,
        operation_factory=operation_context_factory,
        diagnostic_recorder=application.state.diagnostic_snapshot_recorder,
    )
    application.state.mcp_session_manager = mcp_manager
    application.router.routes.append(Route("/mcp", endpoint=mcp_application))
    application.state.conversation_chat = create_conversation_chat(
        executor,
        conversation_runtime,
        operation_context_factory,
        application.state.diagnostic_snapshot_recorder,
        runtime_settings.resolved_cache_url,
        application.state.job_dispatcher_wakeup,
    )
    application.state.onboarding_finisher = create_onboarding_finisher()
    application.state.billing_usage_workflow = create_billing_usage_workflow(
        executor=executor,
    )
    application.state.paper_ingestion_workflow = ingestion_workflow
    application.state.citation_workflow = citation_workflow
    application.state.paper_discovery_workflow = create_paper_discovery_workflow(
        executor=executor,
        settings=runtime_settings,
        operation_factory=operation_context_factory,
        openalex=user_openalex,
    )
    application.state.research_generation_workflow = (
        create_research_generation_workflow(executor, operation_context_factory)
    )
    application.state.translation_workflow = create_translation_workflow(
        executor,
        runtime_settings,
        application.state.diagnostic_snapshot_recorder,
    )
    application.state.zotero_workflow = create_zotero_workflow(
        executor,
        operation_context_factory,
        runtime_settings,
    )
    application.state.job_completion_processor = create_job_completion_processor(
        executor,
        connector_tool_resolver,
        operation_context_factory,
        user_openalex,
    )
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "X-Correlation-ID",
            "X-Request-ID",
            "Preference-Applied",
            "X-Next-Cursor",
        ],
        allow_credentials=True,
        max_age=600,
    )
    application.add_middleware(
        RequestObservabilityMiddleware,
        service="scholens-api",
        environment=runtime_settings.environment,
        release=runtime_settings.release_sha,
        success_sample_rate=runtime_settings.diagnostic_success_sample_rate,
    )
    # Instrument last so the OpenTelemetry ASGI middleware owns the outer
    # request span before structured request logs bind their trace fields.
    configure_application_observability(application, runtime_settings)
    application.include_router(
        _public_router(),
        prefix=PUBLIC_API_PREFIX,
    )
    application.include_router(
        v2_turn_router,
        prefix="/api/v2/conversations",
        tags=["conversations-v2"],
    )
    application.include_router(
        jobs_callback_router,
        prefix=INTERNAL_API_PREFIX,
        include_in_schema=False,
    )

    @application.get("/livez", include_in_schema=False)
    def livez() -> dict[str, str]:
        return {"status": "ok"}

    @application.get(f"{PUBLIC_API_PREFIX}/healthz", include_in_schema=False)
    def public_healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    setup_admin(application)
    return application
