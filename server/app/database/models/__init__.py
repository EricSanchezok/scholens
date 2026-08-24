"""Typed SQLAlchemy model registry for the Scholens product schema."""

from app.shared.domain import JsonScalar, JsonValue
from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadStatus,
    ConversationScopeType,
    DocumentProcessingStatus,
    HighlightType,
    JobDispatchStatus,
    JobOperation,
    JobStatus,
    PaperStatus,
    ReasoningLevel,
    ResearchAudienceType,
    ResearchItemKind,
    RoleType,
    SubscriptionPlan,
    SubscriptionStatus,
    StripeWebhookEventStatus,
    ZoteroAnnotationSyncStatus,
    ZoteroImportSource,
    ZoteroImportStatus,
)
from app.modules.identity.infrastructure.models import AuthUser, UserProfile
from app.modules.access_keys.infrastructure.models import AccessKey
from app.modules.integrations.connections.infrastructure.models import (
    IntegrationConnection,
)
from app.modules.operation_journal.infrastructure.models import (
    OperationJournalEntryModel,
)
from app.modules.identity.infrastructure.onboarding_model import Onboarding
from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobDispatch,
    JobsWebhookNonce,
)
from app.modules.integrations.zotero.infrastructure.models import (
    ZoteroImportedItem,
    ZoteroOAuthPending,
)
from app.modules.conversations.infrastructure.models import (
    Conversation,
    ConversationContextDocument,
    ConversationContextProject,
    ConversationResponse,
    ConversationTurn,
)
from app.modules.papers.infrastructure.models import (
    LibraryPaper,
    LibraryPaperTag,
    Document,
    DocumentPassage,
    DocumentSearchEmbedding,
    PaperTag,
    UploadReservation,
)
from app.modules.papers.infrastructure.preferences import PaperListPreference
from app.modules.papers.infrastructure.upload_sessions import PaperUploadSession
from app.modules.billing.infrastructure.usage_models import (
    TokenUsageEvent,
    TokenWeeklyUsage,
)
from app.modules.projects.infrastructure.models import (
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    CitationOutput,
    AnnotationThread,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
)
from app.modules.billing.infrastructure.models import (
    AccountPlanGrant,
    AccountQuotaOverride,
    StripeWebhookEvent,
    Subscription,
)
from app.database.models.tool_invocation import ToolInvocation
from app.database.models.action_confirmation import ActionConfirmation
from app.modules.translations.infrastructure.models import (
    TranslationPreference,
    TranslationResult,
)
from app.modules.reflows.infrastructure.models import (
    DocumentReflow,
    DocumentReflowBlock,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingActivityPreference,
    ReadingMetricDefinition,
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
    ReadingSessionHour,
    ReadingSessionPage,
)

__all__ = [
    "AuthUser",
    "AccessKey",
    "ActionConfirmation",
    "AnnotationColor",
    "AnnotationThreadStatus",
    "AccountPlanGrant",
    "AccountQuotaOverride",
    "Base",
    "ConversationScopeType",
    "IntegrationConnection",
    "DocumentProcessingStatus",
    "Conversation",
    "ConversationContextDocument",
    "ConversationContextProject",
    "HighlightType",
    "DurableJob",
    "JobDispatch",
    "JobDispatchStatus",
    "JobOperation",
    "JobStatus",
    "JobsWebhookNonce",
    "LibraryPaper",
    "LibraryPaperTag",
    "JsonScalar",
    "JsonValue",
    "ConversationResponse",
    "ConversationTurn",
    "Onboarding",
    "OperationJournalEntryModel",
    "Document",
    "DocumentPassage",
    "DocumentSearchEmbedding",
    "DocumentReflow",
    "DocumentReflowBlock",
    "PaperStatus",
    "PaperTag",
    "PaperListPreference",
    "PaperUploadSession",
    "UploadReservation",
    "Project",
    "ProjectCollaborator",
    "ProjectInvitation",
    "ProjectPaper",
    "ReasoningLevel",
    "ReadingActivityPreference",
    "ReadingMetricDefinition",
    "ReadingPersonalHourRollup",
    "ReadingPersonalPageRollup",
    "ReadingProjectHourRollup",
    "ReadingProjectPageRollup",
    "ReadingProjectPersonalPageRollup",
    "ReadingSession",
    "ReadingSessionHour",
    "ReadingSessionPage",
    "ResearchAudioOverview",
    "ResearchDataTable",
    "ResearchItem",
    "ResearchAudienceType",
    "ResearchItemKind",
    "CitationOutput",
    "AnnotationThread",
    "AnnotationComment",
    "RoleType",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "StripeWebhookEvent",
    "StripeWebhookEventStatus",
    "TokenUsageEvent",
    "TokenWeeklyUsage",
    "ToolInvocation",
    "TranslationPreference",
    "TranslationResult",
    "UserProfile",
    "ZoteroImportSource",
    "ZoteroImportStatus",
    "ZoteroAnnotationSyncStatus",
    "ZoteroImportedItem",
    "ZoteroOAuthPending",
]
