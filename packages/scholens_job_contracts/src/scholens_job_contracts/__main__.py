"""Print queue names for shell entrypoints without duplicating the contract."""

from scholens_job_contracts import JOB_QUEUE_NAMES


def main() -> None:
    print(",".join(sorted(str(queue) for queue in JOB_QUEUE_NAMES)))


if __name__ == "__main__":
    main()
