"""The only production queue names understood by Server and Jobs."""

from enum import StrEnum


class JobQueue(StrEnum):
    DOCUMENT = "document"
    RESEARCH = "research"
    MAINTENANCE = "maintenance"


JOB_QUEUE_NAMES = frozenset(JobQueue)
