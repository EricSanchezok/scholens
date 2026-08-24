"""One-shot EventBridge entry point for hourly Server-owned maintenance."""

from __future__ import annotations

import logging
import os
import time

from src.webhook_signing import callback_base_url, post_signed_json

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_BATCH_SIZE = 100
MAX_RETENTION_BATCHES_PER_RUN = 1000
MAX_RETENTION_NO_PROGRESS_ATTEMPTS = 3
RETENTION_NO_PROGRESS_BACKOFF_SECONDS = 0.25


def main() -> int:
    webhook_base = callback_base_url()
    failures: list[Exception] = []
    try:
        _schedule_due_zotero_syncs(webhook_base)
    except Exception as exc:  # noqa: BLE001 - both duties must be attempted
        logger.exception("job.maintenance.zotero.failed")
        failures.append(exc)
    try:
        _drain_reading_activity_retention(webhook_base)
    except Exception as exc:  # noqa: BLE001 - report after the other duty runs
        logger.exception("job.maintenance.reading_retention.failed")
        failures.append(exc)
    if failures:
        raise RuntimeError("hourly_server_maintenance_failed") from failures[0]
    return 0


def _schedule_due_zotero_syncs(webhook_base: str) -> None:
    sync_interval = int(os.getenv("ZOTERO_SYNC_INTERVAL_SECONDS", str(24 * 60 * 60)))
    url = (
        f"{webhook_base}/internal/v1/schedules/zotero-sync"
        f"?threshold_seconds={sync_interval}"
    )
    logger.info("job.maintenance.zotero.started")
    response = post_signed_json(url, timeout=120)
    try:
        response.raise_for_status()
        scheduled_job_count = response.json().get("scheduled_jobs", 0)
    finally:
        response.close()
    logger.info(
        "job.maintenance.zotero.completed",
        extra={"scheduled_job_count": scheduled_job_count},
    )


def _drain_reading_activity_retention(webhook_base: str) -> None:
    batch_size = int(
        os.getenv(
            "READING_ACTIVITY_RETENTION_BATCH_SIZE",
            str(DEFAULT_RETENTION_BATCH_SIZE),
        )
    )
    if not 1 <= batch_size <= DEFAULT_RETENTION_BATCH_SIZE:
        raise RuntimeError("invalid_reading_activity_retention_batch_size")
    url = (
        f"{webhook_base}/internal/v1/schedules/reading-activity-retention"
        f"?batch_size={batch_size}"
    )
    purged_sessions = 0
    purged_pages = 0
    no_progress_attempts = 0
    for batch_number in range(1, MAX_RETENTION_BATCHES_PER_RUN + 1):
        response = post_signed_json(url, timeout=120)
        try:
            response.raise_for_status()
            result = response.json()
        finally:
            response.close()
        batch_purged_sessions = int(result.get("purged_sessions", 0))
        remaining_candidates = int(result.get("remaining_candidates", 0))
        if remaining_candidates > 0 and batch_purged_sessions == 0:
            no_progress_attempts += 1
            if no_progress_attempts >= MAX_RETENTION_NO_PROGRESS_ATTEMPTS:
                raise RuntimeError("reading_activity_retention_no_progress")
            time.sleep(RETENTION_NO_PROGRESS_BACKOFF_SECONDS * no_progress_attempts)
            continue
        no_progress_attempts = 0
        purged_sessions += batch_purged_sessions
        purged_pages += int(result.get("purged_pages", 0))
        if remaining_candidates == 0:
            logger.info(
                "job.maintenance.reading_retention.completed",
                extra={
                    "batch_count": batch_number,
                    "purged_session_count": purged_sessions,
                    "purged_page_count": purged_pages,
                },
            )
            return
    raise RuntimeError("reading_activity_retention_drain_incomplete")


if __name__ == "__main__":
    raise SystemExit(main())
