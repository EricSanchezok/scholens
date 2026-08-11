"""
Celery tasks for Scholens jobs
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from functools import partial
from typing import Any

import psutil
import requests
from celery.exceptions import SoftTimeLimitExceeded

from src.schemas import DataTableSchema, DataTableTaskRequest, ResearchDataTableResult
from src.audio import generate_audio
from src.data_table_processor import construct_data_table
from src.pdf.models import (
    ParserError,
    ParserTransientError,
)
from src.pdf.pipeline import process_pdf_file
from src.pdf.state import ParserStateStore
from src.celery_app import celery_app, ZOTERO_SYNC_INTERVAL_SECONDS
from src.s3_service import s3_service
from src.token_usage import collect_token_usage
from src.utils import time_it
from src.webhook_signing import post_signed_json
from src.schemas import AudioOverviewRequest

logger = logging.getLogger(__name__)

PDF_TASK_SOFT_TIME_LIMIT_SECONDS = 1200
PDF_TASK_TIME_LIMIT_SECONDS = 1260
JOB_HEARTBEAT_SECONDS = 30
JOB_PROGRESS_TIMEOUT_SECONDS = 5
PDF_PROGRESS_MARKERS = (
    # Match terminal and specific stages before broad provider status text.
    # "PDF processing complete" intentionally contains "processing".
    ("complete", "finalizing"),
    ("extracting", "extracting_metadata"),
    ("read ", "extracting_metadata"),
    ("indexing", "indexing"),
    ("downloading", "downloading"),
    ("parsing", "parsing"),
    ("mineru", "parsing"),
    ("fallback", "parsing"),
    ("processing", "parsing"),
)


def _normalize_pdf_progress(status: str, *, current: str) -> str:
    normalized = status.casefold()
    return next(
        (
            code
            for marker, code in PDF_PROGRESS_MARKERS
            if marker in normalized
        ),
        current,
    )


class JobCancelled(Exception):
    """Raised at a cooperative boundary after Server cancels an ingestion."""


class ProgressReporter:
    def __init__(
        self,
        *,
        task: Any,
        task_id: str,
        progress_url: str,
    ) -> None:
        self._task = task
        self._task_id = task_id
        self._progress_url = progress_url
        self._progress_code = "downloading"
        self._stop = threading.Event()
        self._cancelled = threading.Event()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"paper-progress-{task_id}",
            daemon=True,
        )

    def __enter__(self) -> "ProgressReporter":
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=JOB_PROGRESS_TIMEOUT_SECONDS + 1)

    def update(self, status: str) -> None:
        _update_status(self._task, self._task_id, status)
        self._progress_code = _normalize_pdf_progress(
            status,
            current=self._progress_code,
        )
        self._post_progress()
        self.check_cancelled()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled("paper_ingestion_cancelled")

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(JOB_HEARTBEAT_SECONDS):
            self._post_progress()

    def _post_progress(self) -> None:
        try:
            response = post_signed_json(
                self._progress_url,
                {"progress_code": self._progress_code},
                timeout=JOB_PROGRESS_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            if not bool(response.json().get("claimed")):
                self._cancelled.set()
        except requests.RequestException:
            logger.warning(
                "job.progress.delivery_failed",
                exc_info=True,
                extra={"job_id": self._task_id},
            )


def _update_status(task: Any, task_id: str, status: str) -> None:
    logger.info("job.status.updating", extra={"job_id": task_id})
    try:
        task.update_state(state="PROGRESS", meta={"status": status})
    except Exception:
        logger.exception("job.status.update_failed", extra={"job_id": task_id})


def _deliver_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
) -> bool:
    try:
        response = post_signed_json(webhook_url, payload, timeout=60)
        response.raise_for_status()
        logger.info("job.webhook.delivered", extra={"job_id": task_id})
        return True
    except requests.RequestException:
        logger.exception("job.webhook.delivery_failed", extra={"job_id": task_id})
        return False


def _claim_job(claim_url: str | None, *, task_id: str) -> bool:
    if claim_url is None:
        return True
    try:
        response = post_signed_json(claim_url, {}, timeout=30)
        response.raise_for_status()
        claimed = bool(response.json().get("claimed"))
        if not claimed:
            logger.info("job.claim.skipped", extra={"job_id": task_id})
        return claimed
    except requests.RequestException:
        logger.exception("job.claim.failed", extra={"job_id": task_id})
        raise


@celery_app.task(
    bind=True,
    name="upload_and_process_file",
    soft_time_limit=PDF_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=PDF_TASK_TIME_LIMIT_SECONDS,
)
def upload_and_process_file(
    self,
    s3_object_key: str,
    webhook_url: str,
    progress_url: str,
    claim_url: str,
    skip_metadata_extraction: bool = False,
) -> dict[str, Any]:
    """
    Process a PDF file from S3 object key and send results to webhook.

    When skip_metadata_extraction is True, the LLM metadata/summary step is
    skipped and only deterministic outputs (preview, raw text, page offsets)
    are produced. Used by the Zotero import path.
    """
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    usage_events: list[dict[str, Any]] = []

    try:
        with ProgressReporter(
            task=self,
            task_id=task_id,
            progress_url=progress_url,
        ) as progress:
            logger.info("job.pdf_processing.started", extra={"job_id": task_id})
            progress.update("Downloading PDF from S3")

            async def download_with_timer():
                async with time_it("Downloading PDF from S3", job_id=task_id):
                    return s3_service.download_file_to_bytes(s3_object_key)

            pdf_bytes = asyncio.run(download_with_timer())
            progress.check_cancelled()

            progress.update("Processing PDF file")

            with collect_token_usage(task_id) as usage:
                usage_events = usage.events
                result = asyncio.run(
                    process_pdf_file(
                        pdf_bytes,
                        s3_object_key,
                        task_id,
                        status_callback=progress.update,
                        skip_metadata_extraction=skip_metadata_extraction,
                    )
                )

            progress.update("PDF processing complete!")
            progress.check_cancelled()

            webhook_payload = {
                "task_id": task_id,
                "status": "completed" if result.success else "failed",
                "result": result.model_dump(),
                "error": result.error if not result.success else None,
                "usage_events": usage_events,
            }

            webhook_delivered = _deliver_webhook(
                webhook_url,
                webhook_payload,
                task_id=task_id,
            )
            if not webhook_delivered:
                webhook_payload["webhook_error"] = "webhook_delivery_failed"
            else:
                try:
                    asyncio.run(_clear_parser_checkpoint(task_id))
                except ParserTransientError as exc:
                    logger.warning(
                        "job.pdf_checkpoint.clear_failed",
                        extra={"job_id": task_id, **exc.diagnostic_fields()},
                    )

            logger.info("job.pdf_processing.completed", extra={"job_id": task_id})
            return webhook_payload

    except JobCancelled:
        logger.info("job.pdf_processing.cancelled", extra={"job_id": task_id})
        try:
            asyncio.run(_clear_parser_checkpoint(task_id))
        except ParserTransientError as cleanup_exc:
            logger.warning(
                "job.pdf_checkpoint.clear_failed",
                extra={"job_id": task_id, **cleanup_exc.diagnostic_fields()},
            )
        return {"task_id": task_id, "status": "cancelled"}

    except SoftTimeLimitExceeded:
        logger.exception("job.pdf_processing.timed_out", extra={"job_id": task_id})
        timeout_payload = {
            "task_id": task_id,
            "status": "failed",
            "result": {
                "success": False,
                "job_id": task_id,
                "error": "pdf_processing_timeout",
            },
            "error": "pdf_processing_timeout",
            "usage_events": usage_events,
        }
        _deliver_webhook(webhook_url, timeout_payload, task_id=task_id)
        raise

    except Exception as exc:
        diagnostics = (
            exc.diagnostic_fields()
            if isinstance(exc, ParserError)
            else {"exception_type": type(exc).__name__}
        )
        logger.exception(
            "job.pdf_processing.failed",
            extra={"job_id": task_id, **diagnostics},
        )
        failure_payload = {
            "task_id": task_id,
            "status": "failed",
            "result": {
                "success": False,
                "job_id": task_id,
                "error": "pdf_processing_failed",
            },
            "error": "pdf_processing_failed",
            "usage_events": usage_events,
        }
        if _deliver_webhook(webhook_url, failure_payload, task_id=task_id):
            try:
                asyncio.run(_clear_parser_checkpoint(task_id))
            except ParserTransientError as cleanup_exc:
                logger.warning(
                    "job.pdf_checkpoint.clear_failed",
                    extra={
                        "job_id": task_id,
                        **cleanup_exc.diagnostic_fields(),
                    },
                )
        raise


async def _clear_parser_checkpoint(job_id: str) -> None:
    state_store = ParserStateStore()
    try:
        await state_store.clear(job_id)
    finally:
        await state_store.close()


@celery_app.task(
    bind=True, name="process_data_table", soft_time_limit=900, time_limit=960
)
def construct_data_table_task(
    self,
    request: dict[str, Any],
    webhook_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    """
    Celery task to construct a data table based on the provided schema.
    """
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    usage_events: list[dict[str, Any]] = []
    write_to_status = partial(_update_status, self, task_id)

    write_to_status("Starting data table construction")

    try:
        task_request = DataTableTaskRequest.model_validate(request)
        data_table = DataTableSchema.model_validate(task_request.table)
        with collect_token_usage(task_id) as usage:
            usage_events = usage.events
            result = asyncio.run(
                construct_data_table(
                    data_table_schema=data_table,
                    status_callback=write_to_status,
                )
            )

        write_to_status("Data table construction complete!")

        research_result = ResearchDataTableResult(
            research_item_id=task_request.research_item_id,
            title=task_request.title,
            columns=result.columns,
            rows=result.rows,
            row_failures=result.row_failures,
        )
        webhook_payload = {
            "task_id": task_id,
            "status": "completed" if result.success else "failed",
            "result": research_result.model_dump(mode="json"),
            "error": None if result.success else "data_table_processing_failed",
            "usage_events": usage_events,
        }

        if not _deliver_webhook(webhook_url, webhook_payload, task_id=task_id):
            webhook_payload["webhook_error"] = "webhook_delivery_failed"

        logger.info("job.data_table.completed", extra={"job_id": task_id})
        return webhook_payload

    except Exception:
        logger.exception("job.data_table.failed", extra={"job_id": task_id})
        failure_payload = {
            "task_id": task_id,
            "status": "failed",
            "result": None,
            "error": "data_table_processing_failed",
            "usage_events": usage_events,
        }

        _deliver_webhook(webhook_url, failure_payload, task_id=task_id)
        raise


@celery_app.task(
    bind=True,
    name="generate_audio_overview",
    soft_time_limit=1800,
    time_limit=1860,
)
def generate_audio_overview_task(
    self,
    request: dict[str, Any],
    webhook_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    """Generate one idempotently-addressed audio research item."""
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}

    usage_events: list[dict[str, Any]] = []
    try:
        parsed_request = AudioOverviewRequest.model_validate(request)
        with collect_token_usage(task_id) as usage:
            usage_events = usage.events
            result = asyncio.run(generate_audio(parsed_request))
        payload = {
            "task_id": task_id,
            "status": "completed",
            "result": result.model_dump(mode="json"),
            "usage_events": usage_events,
        }
        if not _deliver_webhook(webhook_url, payload, task_id=task_id):
            payload["webhook_error"] = "webhook_delivery_failed"
        return payload
    except Exception:
        logger.exception("job.audio_overview.failed", extra={"job_id": task_id})
        payload = {
            "task_id": task_id,
            "status": "failed",
            "result": None,
            "error": "audio_generation_failed",
            "usage_events": usage_events,
        }
        _deliver_webhook(webhook_url, payload, task_id=task_id)
        raise


@celery_app.task(bind=True, name="postprocess_pdf")
def postprocess_pdf_task(
    self,
    callback_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    """Trigger idempotent Server-side persistence work under a durable lease."""
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    payload = {"task_id": task_id}
    if not _deliver_webhook(callback_url, payload, task_id=task_id):
        raise RuntimeError("pdf_postprocess_callback_failed")
    return {**payload, "status": "completed"}


@celery_app.task(bind=True, name="collect_document")
def collect_document_task(
    self,
    callback_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    """Execute reference-safe, idempotent storage collection through Server."""
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    payload = {"task_id": task_id}
    if not _deliver_webhook(callback_url, payload, task_id=task_id):
        raise RuntimeError("document_gc_callback_failed")
    return {**payload, "status": "completed"}


@celery_app.task(bind=True, name="delete_storage_objects")
def delete_storage_objects_task(
    self,
    object_keys: list[str],
    callback_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    """Idempotently remove generated objects and acknowledge the durable job."""
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    failed = [key for key in object_keys if not s3_service.delete_file(key)]
    if failed:
        logger.error(
            "storage.cleanup.failed",
            extra={"job_id": task_id, "failed_object_count": len(failed)},
        )
        raise RuntimeError("storage_delete_failed")
    payload = {"task_id": task_id, "deleted_count": len(object_keys)}
    if not _deliver_webhook(callback_url, payload, task_id=task_id):
        raise RuntimeError("storage_delete_callback_failed")
    return {**payload, "status": "completed"}


@celery_app.task(bind=True, name="health_check")
def health_check(self):
    """
    Health check task to monitor worker status.
    Returns system metrics and worker health status.
    """
    try:
        # Get system metrics
        memory_info = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        disk_usage = psutil.disk_usage("/")

        # Get process info
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()

        health_data = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker_id": self.request.hostname,
            "task_id": self.request.id,
            "system_metrics": {
                "memory_percent": memory_info.percent,
                "memory_available_mb": memory_info.available / (1024 * 1024),
                "cpu_percent": cpu_percent,
                "disk_percent": disk_usage.percent,
            },
            "process_metrics": {
                "memory_mb": process_memory.rss / (1024 * 1024),
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
            },
        }

        # Check if worker is unhealthy
        if (
            memory_info.percent > 90
            or cpu_percent > 95
            or process_memory.rss / (1024 * 1024) > 1500
        ):
            health_data["status"] = "unhealthy"
            health_data["alert"] = "High resource usage detected"

        return health_data

    except Exception:
        logger.exception("jobs.health_check.failed")
        return {
            "status": "unhealthy",
            "error": "health_check_failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker_id": self.request.hostname,
        }


@celery_app.task(bind=True, name="periodic_zotero_sync")
def periodic_zotero_sync(self):
    """Ask Server to persist due per-user Zotero jobs in its outbox."""
    webhook_base = os.getenv("WEBHOOK_BASE_URL", "http://127.0.0.1:7301")
    sync_interval = int(ZOTERO_SYNC_INTERVAL_SECONDS)
    url = (
        f"{webhook_base}/internal/v1/schedules/zotero-sync"
        f"?threshold_seconds={sync_interval}"
    )
    logger.info("job.zotero_schedule.started")
    resp = post_signed_json(url, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    logger.info(
        "job.zotero_schedule.completed",
        extra={"scheduled_job_count": result.get("scheduled_jobs", 0)},
    )
    return result


@celery_app.task(bind=True, name="postprocess_zotero")
def postprocess_zotero_task(
    self,
    callback_url: str,
    claim_url: str | None = None,
) -> dict[str, Any]:
    task_id = self.request.id
    if not _claim_job(claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    payload = {"task_id": task_id}
    if not _deliver_webhook(callback_url, payload, task_id=task_id):
        raise RuntimeError("zotero_postprocess_callback_failed")
    return {**payload, "status": "completed"}
