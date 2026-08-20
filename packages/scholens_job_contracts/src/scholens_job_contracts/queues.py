"""The only production queue names understood by Server and Jobs."""

from enum import StrEnum


class JobQueue(StrEnum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    RESEARCH = "research"
    MAINTENANCE = "maintenance"


JOB_QUEUE_NAMES = frozenset(JobQueue)
JOBS_WORKER_QUEUE_NAMES = frozenset(
    {JobQueue.DOCUMENT, JobQueue.RESEARCH, JobQueue.MAINTENANCE}
)
