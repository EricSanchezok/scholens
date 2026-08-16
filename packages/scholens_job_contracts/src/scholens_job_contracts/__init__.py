"""Shared, service-neutral background-job contracts."""

from scholens_job_contracts.queues import JOB_QUEUE_NAMES, JobQueue

__all__ = ["JOB_QUEUE_NAMES", "JobQueue"]
