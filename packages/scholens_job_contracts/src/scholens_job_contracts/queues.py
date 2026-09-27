"""The only production queue names understood by Server and Jobs."""

from enum import StrEnum


class JobQueue(StrEnum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    DOCUMENT_INDEX = "document-index"
    DOCUMENT_ENRICHMENT = "document-enrichment"
    RESEARCH = "research"
    MAINTENANCE = "maintenance"


JOB_QUEUE_NAMES = frozenset(JobQueue)
JOBS_WORKER_QUEUE_NAMES = frozenset(
    {
        JobQueue.DOCUMENT,
        JobQueue.DOCUMENT_INDEX,
        JobQueue.DOCUMENT_ENRICHMENT,
        JobQueue.RESEARCH,
        JobQueue.MAINTENANCE,
    }
)
