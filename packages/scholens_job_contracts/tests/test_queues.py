from scholens_job_contracts import JOB_QUEUE_NAMES, JobQueue


def test_queue_contract_is_closed_and_string_compatible() -> None:
    assert JOB_QUEUE_NAMES == {
        JobQueue.DOCUMENT,
        JobQueue.RESEARCH,
        JobQueue.MAINTENANCE,
    }
    assert {str(queue) for queue in JOB_QUEUE_NAMES} == {
        "document",
        "research",
        "maintenance",
    }
