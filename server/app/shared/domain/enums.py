from enum import Enum


class SubscriptionPlan(str, Enum):
    BASIC = "basic"
    RESEARCHER = "researcher"


# When a user has a RESEARCHER (or more advanced) subscription,
# they can have one of the following statuses.


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class StripeWebhookEventStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"


class ReasoningLevel(str, Enum):
    STANDARD = "standard"
    DEEP = "deep"


class ZoteroImportSource(str, Enum):
    PDF_ATTACHMENT = "pdf_attachment"
    URL = "url"


class ZoteroImportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ZoteroAnnotationSyncStatus(str, Enum):
    ACTIVE = "active"
    SOURCE_UNAVAILABLE = "source_unavailable"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobOperation(str, Enum):
    CONVERSATION_GENERATE = "conversation_generate"
    PDF_PROCESS = "pdf_process"
    PDF_POSTPROCESS = "pdf_postprocess"
    DOCUMENT_REFLOW = "document_reflow"
    AUDIO_GENERATE = "audio_generate"
    DATA_TABLE_GENERATE = "data_table_generate"
    ZOTERO_IMPORT = "zotero_import"
    ZOTERO_SYNC = "zotero_sync"
    DOCUMENT_GC = "document_gc"
    STORAGE_DELETE = "storage_delete"


class JobDispatchStatus(str, Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


class DocumentProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RoleType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class PaperStatus(str, Enum):
    todo = "todo"
    reading = "reading"
    completed = "completed"


class ConversationScopeType(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"
    PAPER = "paper"


class ResearchItemKind(str, Enum):
    ANNOTATION_THREAD = "annotation_thread"
    CITATION = "citation"
    AUDIO_OVERVIEW = "audio_overview"
    DATA_TABLE = "data_table"


class ResearchAudienceType(str, Enum):
    PERSONAL = "personal"
    DOCUMENT = "document"
    PROJECT = "project"


class AnnotationThreadStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class AnnotationThreadMode(str, Enum):
    HIGHLIGHT = "highlight"
    NOTE = "note"
    DISCUSSION = "discussion"


class AnnotationAudienceFilter(str, Enum):
    PERSONAL = "personal"
    PROJECT = "project"


class AnnotationColor(str, Enum):
    YELLOW = "yellow"
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    PURPLE = "purple"
    MAGENTA = "magenta"
    ORANGE = "orange"
    GRAY = "gray"


class HighlightType(str, Enum):
    TOPIC = "topic"
    MOTIVATION = "motivation"
    METHOD = "method"
    EVIDENCE = "evidence"
    RESULT = "result"
    IMPACT = "impact"
    GENERAL = "general"
