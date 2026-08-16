"""The application's single composition root.

Transport adapters import builders from this module and never choose concrete
infrastructure themselves. Keeping every adapter decision here makes storage,
search, identity, billing, and integrations replaceable without changing an
HTTP, Agent, or MCP contract.
"""

from __future__ import annotations

from functools import partial
from typing import Literal
from uuid import UUID

from app.modules.papers.application.search import PaperSearchAccessPort, PaperSearchPort
from app.modules.papers.application.collection_access import PaperCollectionAccessPort
from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.infrastructure.content_gateway import (
    SqlAlchemyPaperContentGateway,
)
from app.modules.papers.application.downloads import GetPaperDownload
from app.modules.papers.infrastructure.downloads import S3PaperDownloadSigner
from app.helpers.s3 import DEFAULT_SIGNED_URL_TTL_SECONDS
from app.modules.papers.application.ingestion import IngestPaper
from app.modules.papers.application.upload_sessions import PaperUploadSessions
from app.modules.papers.infrastructure.upload_sessions import SqlPaperUploadGateway
from app.bootstrap.adapters.paper_ingestion import (
    DefaultPaperSourceResolver,
    DefaultPaperIngestionLimits,
    DefaultPdfInputValidator,
    SafePdfUrlSource,
    SqlPaperIngestionGateway,
)
from app.bootstrap.adapters.paper_search import PostgresPaperSearch
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.modules.projects.infrastructure.document_visibility import (
    SqlProjectDocumentVisibility,
)
from app.modules.research.application.search import (
    SearchResearch,
    build_research_search_cursor,
)
from app.bootstrap.adapters.research_search import SqlResearchSearch
from app.modules.identity.application.onboarding import (
    FinishOnboarding,
    SaveOnboarding,
)
from app.modules.identity.infrastructure.onboarding_adapters import (
    CloudAuthDisplayNameWriter,
    PostHogOnboardingEventRecorder,
    SqlAlchemyOnboardingWriter,
)
from app.modules.billing.application.billing import Billing
from app.modules.billing.application.entitlement_admin import EntitlementAdmin
from app.modules.billing.infrastructure.application_gateway import (
    SqlAlchemySubscriptionStore,
    SqlAlchemyUsageReader,
)
from app.modules.billing.infrastructure.config import (
    MONTHLY_PRICE_ID,
    YEARLY_PRICE_ID,
)
from app.modules.papers.application.tags import LibraryTags
from app.modules.papers.infrastructure.tag_gateway import (
    SqlAlchemyLibraryTagGateway,
)
from app.modules.papers.application.discovery import (
    DiscoverPapers,
    ExternalPaperCatalog,
    ExternalPaperDiscovery,
)
from app.modules.papers.infrastructure.discovery import (
    AiExternalDiscoveryRateLimiter,
    PostHogDiscoveryEventRecorder,
    SqlDiscoveryDocumentGateway,
)
from app.modules.papers.application.details import GetPaperDetails
from app.modules.papers.application.citations import CitationMetadata
from app.modules.papers.application.library import PaperLibrary
from app.modules.papers.infrastructure.details import SqlAlchemyPaperDetails
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
)
from app.modules.papers.application.maintenance import PassageMaintenance
from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill
from app.bootstrap.adapters.library_outputs import SqlAlchemyLibraryOutputsGateway
from app.bootstrap.adapters.library_removal import (
    delete_personal_document_annotations,
)
from app.bootstrap.adapters.document_gc import schedule_document_gc
from app.modules.projects.application.projects import Projects
from app.bootstrap.adapters.project_gateway import (
    SqlAlchemyProjectGateway,
)
from app.modules.research.application.items import ResearchItems
from app.bootstrap.adapters.research_items import (
    SqlAlchemyResearchItemGateway,
)
from app.modules.jobs.application.jobs import Jobs
from app.modules.jobs.application.callbacks import JobCallbacks
from app.modules.jobs.application.authentication import ProtectJobCallback
from app.modules.jobs.infrastructure.application_gateway import (
    SqlAlchemyJobsGateway,
)
from app.modules.research.application.generation import (
    GenerationDocuments,
    ResearchGeneration,
)
from app.modules.research.infrastructure.generation import (
    RedisGenerationCapacity,
    SqlGenerationEntitlements,
)
from app.modules.conversations.application.conversations import Conversations
from app.modules.conversations.application.chat import ConversationChatData
from app.bootstrap.adapters.conversation_lifecycle import (
    SqlAlchemyConversationGateway,
)
from app.shared.application import SignedCursorCodec
from app.modules.identity.application.identity import Identity
from app.modules.identity.infrastructure.application_gateway import (
    SqlAlchemyIdentityGateway,
)
from app.modules.access_keys.application.access_keys import AccessKeys
from app.modules.access_keys.infrastructure import (
    SecureAccessKeySecrets,
    SqlAlchemyAccessKeyGateway,
)
from app.modules.integrations.connections.application import Integrations
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure import (
    AesGcmIntegrationCredentialCipher,
    SqlAlchemyIntegrationGateway,
)
from app.modules.operation_journal.application import OperationJournal
from app.shared.infrastructure import SystemClock
from app.shared.domain import FailureKind
from app.modules.identity.infrastructure import (
    sanchezcloud_identity as sanchezcloud_identity_adapter,
)
from app.modules.papers.application.topics import PaperTopics
from app.modules.papers.infrastructure.topics import SqlAlchemyPaperTopics
from app.modules.integrations.zotero.application.zotero import Zotero
from app.modules.translations.application import Translations
from app.modules.translations.infrastructure.repository import (
    SqlAlchemyTranslationPreferences,
)
from app.modules.translations.infrastructure.entitlements import (
    SqlTranslationEntitlements,
)
from app.modules.reflows.application import DocumentReflows
from app.modules.reflows.application.reflows import ReflowIntegrationAccess
from app.bootstrap.adapters.document_reflow import SqlDocumentReflowGateway
from app.bootstrap.adapters.zotero_gateway import (
    DefaultZoteroGateway,
)
from app.bootstrap.adapters.billing_capacity import (
    BillingLibraryCapacity,
    BillingProjectCapacity,
    BillingZoteroImportCapacity,
)
from sqlalchemy.orm import Session
from app.modules.action_confirmations.application import ActionConfirmations
from app.modules.action_confirmations.infrastructure import ActionConfirmationRepository

optional_identity_user_dependency = (
    sanchezcloud_identity_adapter.get_optional_identity_user
)


def build_action_confirmations(*, db: Session) -> ActionConfirmations:
    return ActionConfirmations(
        repository=ActionConfirmationRepository(db),
        clock=SystemClock(),
    )


def build_paper_search(
    *,
    backend: Literal["postgres_fts"],
    db: Session,
) -> PaperSearchPort:
    if backend == "postgres_fts":
        return PostgresPaperSearch(db)
    raise ValueError(f"Unsupported paper search backend: {backend}")


def build_paper_search_access(*, db: Session) -> PaperSearchAccessPort:
    from app.bootstrap.adapters.paper_search_access import SqlPaperSearchAccess

    return SqlPaperSearchAccess(db)


def build_paper_collection_access(*, db: Session) -> PaperCollectionAccessPort:
    from app.bootstrap.adapters.paper_collection_access import (
        SqlPaperCollectionAccess,
    )

    return SqlPaperCollectionAccess(db)


def build_project_document_visibility(
    *,
    db: Session,
) -> ListAccessibleProjectDocuments:
    return ListAccessibleProjectDocuments(SqlProjectDocumentVisibility(db))


def build_paper_content(*, db: Session) -> PaperContentCapabilities:
    return PaperContentCapabilities(
        SqlAlchemyPaperContentGateway(db),
        build_project_document_visibility(db=db),
    )


def build_paper_download(*, db: Session) -> GetPaperDownload:
    return GetPaperDownload(
        build_paper_content(db=db),
        S3PaperDownloadSigner(),
        expires_in_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS,
    )


def build_paper_ingestion(*, db: Session, journal: OperationJournal) -> IngestPaper:
    return IngestPaper(
        validator=DefaultPdfInputValidator(),
        limits=DefaultPaperIngestionLimits(),
        gateway=SqlPaperIngestionGateway(db),
        journal=journal,
    )


def build_paper_upload_sessions(*, db: Session) -> PaperUploadSessions:
    from app.helpers.s3 import s3_service
    from app.modules.projects.infrastructure.access import require_project_permission

    def require_project_upload(project_id: UUID, user_id: int) -> None:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=user_id,
            permission="manage_papers",
        )

    return PaperUploadSessions(
        gateway=SqlPaperUploadGateway(
            db,
            require_project_upload=require_project_upload,
        ),
        store=s3_service,
        clock=SystemClock(),
    )


def build_passage_maintenance(
    *, db: Session, journal: OperationJournal
) -> PassageMaintenance:
    return PassageMaintenance(SqlPassageBackfill(db), journal=journal)


def build_pdf_url_source() -> SafePdfUrlSource:
    return SafePdfUrlSource()


def build_paper_source_resolver(*, openalex: object) -> DefaultPaperSourceResolver:
    from app.bootstrap.adapters.openalex import UserOpenAlex

    assert isinstance(openalex, UserOpenAlex)
    return DefaultPaperSourceResolver(openalex=openalex)


def build_research_search(
    *,
    db: Session,
    cursor_secret: str,
) -> SearchResearch:
    return SearchResearch(
        SqlResearchSearch(db),
        build_research_search_cursor(cursor_secret),
    )


def build_save_onboarding(
    *,
    db: Session,
    journal: OperationJournal,
) -> SaveOnboarding:
    return SaveOnboarding(
        writer=SqlAlchemyOnboardingWriter(db),
        journal=journal,
    )


def build_finish_onboarding() -> FinishOnboarding:
    return FinishOnboarding(
        display_names=CloudAuthDisplayNameWriter(),
        events=PostHogOnboardingEventRecorder(),
    )


def build_billing(*, db: Session, journal: OperationJournal) -> Billing:
    return Billing(
        subscriptions=SqlAlchemySubscriptionStore(db),
        usage=SqlAlchemyUsageReader(db),
        journal=journal,
        monthly_price_id=MONTHLY_PRICE_ID,
        yearly_price_id=YEARLY_PRICE_ID,
    )


def build_entitlement_admin(
    *,
    db: Session,
    journal: OperationJournal,
) -> EntitlementAdmin:
    from app.modules.billing.infrastructure.entitlement_admin_gateway import (
        SqlAlchemyEntitlementAdminGateway,
    )
    from app.modules.identity.infrastructure.application_gateway import (
        SqlAlchemyIdentityGateway,
    )

    return EntitlementAdmin(
        SqlAlchemyEntitlementAdminGateway(
            db,
            lock_target_identity=SqlAlchemyIdentityGateway(db).lock_actor_identity,
        ),
        journal=journal,
        clock=SystemClock(),
    )


def build_library_tags(*, db: Session, journal: OperationJournal) -> LibraryTags:
    return LibraryTags(
        SqlAlchemyLibraryTagGateway(db),
        journal=journal,
    )


def build_paper_discovery(
    *,
    db: Session,
    journal: OperationJournal,
) -> DiscoverPapers:
    return DiscoverPapers(
        documents=SqlDiscoveryDocumentGateway(db),
        journal=journal,
    )


def build_external_paper_discovery(
    *,
    cursor_secret: str,
    catalog: ExternalPaperCatalog,
) -> ExternalPaperDiscovery:
    return ExternalPaperDiscovery(
        catalog=catalog,
        rate_limiter=AiExternalDiscoveryRateLimiter(),
        events=PostHogDiscoveryEventRecorder(),
        cursors=SignedCursorCodec(
            cursor_secret,
            revision="external-discovery-v1",
            error_code="discovery_cursor_expired",
        ),
    )


def build_paper_library(
    *,
    db: Session,
    cursor_secret: str,
    journal: OperationJournal,
) -> PaperLibrary:
    return PaperLibrary(
        gateway=SqlAlchemyPaperLibraryGateway(
            db,
            document_removed=partial(schedule_document_gc, db),
            personal_annotations_removed=partial(
                delete_personal_document_annotations,
                db,
            ),
        ),
        outputs=SqlAlchemyLibraryOutputsGateway(db),
        capacity=BillingLibraryCapacity(db),
        signer=S3PaperDownloadSigner(),
        cursors=SignedCursorCodec(
            cursor_secret,
            revision="library-v1",
            error_code="library_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=journal,
    )


def build_paper_details(*, db: Session) -> GetPaperDetails:
    return GetPaperDetails(
        SqlAlchemyPaperDetails(db),
        build_project_document_visibility(db=db),
    )


def build_document_reflows(
    *,
    db: Session,
    journal: OperationJournal,
    require_mineru: ReflowIntegrationAccess,
) -> DocumentReflows:
    return DocumentReflows(
        access=build_paper_details(db=db),
        gateway=SqlDocumentReflowGateway(db),
        require_mineru=require_mineru,
        journal=journal,
    )


def build_citation_metadata(
    *,
    db: Session,
    journal: OperationJournal,
) -> CitationMetadata:
    from app.bootstrap.adapters.citation_metadata import (
        SqlAlchemyCitationMetadataStore,
    )

    return CitationMetadata(
        SqlAlchemyCitationMetadataStore(db),
        journal=journal,
    )


def build_projects(
    *,
    db: Session,
    cursor_secret: str,
    invitation_token_secret: str,
    journal: OperationJournal,
) -> Projects:
    from app.modules.projects.application.invitation_tokens import (
        ProjectInvitationTokenCodec,
    )

    return Projects(
        gateway=SqlAlchemyProjectGateway(
            db,
            invitation_tokens=ProjectInvitationTokenCodec(invitation_token_secret),
        ),
        capacity=BillingProjectCapacity(db),
        signer=S3PaperDownloadSigner(),
        cursors=SignedCursorCodec(
            cursor_secret,
            revision="projects-v1",
            error_code="project_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=journal,
    )


def build_research_items(*, db: Session, journal: OperationJournal) -> ResearchItems:
    return ResearchItems(
        SqlAlchemyResearchItemGateway(db),
        journal=journal,
    )


def build_jobs(*, db: Session) -> Jobs:
    return Jobs(SqlAlchemyJobsGateway(db))


def build_job_callback_protection() -> ProtectJobCallback:
    from app.modules.jobs.infrastructure.authentication import (
        SqlAlchemyCallbackNonceStore,
    )

    return ProtectJobCallback(SqlAlchemyCallbackNonceStore())


def build_job_callbacks(
    *,
    db: Session,
    journal: OperationJournal,
    integrations: Integrations,
) -> JobCallbacks:
    # Callback adapters touch several domain modules and are loaded only by
    # the internal callback transport, avoiding composition-root import cycles.
    from app.modules.jobs.application.callbacks import RegisteredJobCallback
    from app.modules.jobs.application.contracts import (
        AudioOverviewWebhookData,
        DataTableWebhookData,
        DocumentReflowWebhookData,
        JobCallbackIdentity,
        PdfProcessingWebhookData,
        StorageDeleteCallback,
    )
    from app.bootstrap.adapters.job_callback_handlers import (
        AudioCompletion,
        DataTableCompletion,
        DocumentReflowCompletion,
        DocumentGcCompletion,
        PdfPostprocessCompletion,
        PdfProcessCompletion,
        SqlAlchemyJobLifecycle,
        StorageDeleteCompletion,
        ZoteroSyncSchedule,
    )
    from app.shared.domain.enums import JobOperation

    return JobCallbacks(
        lifecycle=SqlAlchemyJobLifecycle(db),
        handlers={
            JobOperation.PDF_PROCESS: RegisteredJobCallback(
                PdfProcessingWebhookData, PdfProcessCompletion(db)
            ),
            JobOperation.PDF_POSTPROCESS: RegisteredJobCallback(
                JobCallbackIdentity, PdfPostprocessCompletion(db)
            ),
            JobOperation.DOCUMENT_GC: RegisteredJobCallback(
                JobCallbackIdentity, DocumentGcCompletion(db)
            ),
            JobOperation.STORAGE_DELETE: RegisteredJobCallback(
                StorageDeleteCallback, StorageDeleteCompletion(db)
            ),
            JobOperation.AUDIO_GENERATE: RegisteredJobCallback(
                AudioOverviewWebhookData, AudioCompletion(db)
            ),
            JobOperation.DATA_TABLE_GENERATE: RegisteredJobCallback(
                DataTableWebhookData, DataTableCompletion(db)
            ),
            JobOperation.DOCUMENT_REFLOW: RegisteredJobCallback(
                DocumentReflowWebhookData, DocumentReflowCompletion(db)
            ),
        },
        schedules=ZoteroSyncSchedule(db),
        journal=journal,
        record_integration_outcome=lambda actor, operation, event: (
            integrations.record_outcome(
                actor=actor,
                operation=operation,
                provider=IntegrationProvider(event.provider),
                credential_revision=event.credential_revision,
                outcome=event.outcome,
                error_code=event.error_code,
            )
        ),
    )


def build_research_generation(
    *,
    db: Session,
    journal: OperationJournal,
) -> ResearchGeneration:
    project_documents = build_project_document_visibility(db=db)
    return ResearchGeneration(
        documents=GenerationDocuments(
            content=build_paper_content(db=db),
            project_documents=project_documents,
        ),
        jobs=SqlAlchemyJobsGateway(db),
        entitlements=SqlGenerationEntitlements(db),
        journal=journal,
    )


def build_generation_capacity() -> RedisGenerationCapacity:
    return RedisGenerationCapacity()


def build_translations(
    *,
    db: Session,
    journal: OperationJournal,
) -> Translations:
    return Translations(
        gateway=SqlAlchemyTranslationPreferences(db),
        entitlements=SqlTranslationEntitlements(db),
        journal=journal,
    )


def build_conversations(
    *,
    db: Session,
    cursor_secret: str,
    journal: OperationJournal,
) -> Conversations:
    return Conversations(
        gateway=SqlAlchemyConversationGateway(db),
        list_cursors=SignedCursorCodec(
            cursor_secret,
            revision="conversation-list-v2",
            error_code="conversation_cursor_expired",
        ),
        turn_cursors=SignedCursorCodec(
            cursor_secret,
            revision="conversation-turns-v1",
            error_code="conversation_turn_cursor_expired",
        ),
        journal=journal,
    )


def build_conversation_chat_data(
    *,
    db: Session,
    journal: OperationJournal,
) -> ConversationChatData:
    from app.bootstrap.adapters.conversation_chat_data import (
        SqlAlchemyConversationChatData,
    )

    return ConversationChatData(
        SqlAlchemyConversationChatData(db),
        journal=journal,
    )


def build_identity(*, db: Session, journal: OperationJournal) -> Identity:
    return Identity(
        SqlAlchemyIdentityGateway(db),
        journal=journal,
    )


def build_access_keys(
    *,
    db: Session,
    cursor_secret: str,
    journal: OperationJournal,
) -> AccessKeys:
    return AccessKeys(
        gateway=SqlAlchemyAccessKeyGateway(db),
        secrets=SecureAccessKeySecrets(),
        actors=build_identity(db=db, journal=journal),
        clock=SystemClock(),
        cursors=SignedCursorCodec(
            cursor_secret,
            revision="access-keys-v2",
            error_code="access_key_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=journal,
    )


def build_integrations(
    *,
    db: Session,
    credential_encryption_key: str,
    scholight_configured: bool,
    journal: OperationJournal,
) -> Integrations:
    return Integrations(
        gateway=SqlAlchemyIntegrationGateway(db),
        cipher=AesGcmIntegrationCredentialCipher(credential_encryption_key),
        clock=SystemClock(),
        journal=journal,
        scholight_configured=scholight_configured,
    )


def build_paper_topics(*, db: Session) -> PaperTopics:
    return PaperTopics(SqlAlchemyPaperTopics(db))


def build_zotero(*, db: Session, journal: OperationJournal) -> Zotero:
    return Zotero(
        gateway=DefaultZoteroGateway(db),
        capacity=BillingZoteroImportCapacity(db),
        idempotency=SqlAlchemyJobsGateway(db),
        journal=journal,
    )
