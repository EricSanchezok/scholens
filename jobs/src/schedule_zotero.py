"""One-shot EventBridge entry point for durable Zotero scheduling."""

from __future__ import annotations

import logging
import os

from src.webhook_signing import callback_base_url, post_signed_json

logger = logging.getLogger(__name__)


def main() -> int:
    webhook_base = callback_base_url()
    sync_interval = int(os.getenv("ZOTERO_SYNC_INTERVAL_SECONDS", str(24 * 60 * 60)))
    url = (
        f"{webhook_base}/internal/v1/schedules/zotero-sync"
        f"?threshold_seconds={sync_interval}"
    )
    logger.info("job.zotero_schedule.started")
    response = post_signed_json(url, timeout=120)
    response.raise_for_status()
    logger.info(
        "job.zotero_schedule.completed",
        extra={"scheduled_job_count": response.json().get("scheduled_jobs", 0)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
