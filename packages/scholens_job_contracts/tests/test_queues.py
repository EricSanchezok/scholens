from scholens_job_contracts import (
    JOB_QUEUE_NAMES,
    JOBS_WORKER_QUEUE_NAMES,
    JobQueue,
)


def test_queue_contract_is_closed_and_string_compatible() -> None:
    assert JOB_QUEUE_NAMES == {
        JobQueue.CONVERSATION,
        JobQueue.DOCUMENT,
        JobQueue.RESEARCH,
        JobQueue.MAINTENANCE,
    }
    assert {str(queue) for queue in JOB_QUEUE_NAMES} == {
        "conversation",
        "document",
        "research",
        "maintenance",
    }


def test_jobs_workers_do_not_consume_server_owned_conversations() -> None:
    assert JOBS_WORKER_QUEUE_NAMES == {
        JobQueue.DOCUMENT,
        JobQueue.RESEARCH,
        JobQueue.MAINTENANCE,
    }
