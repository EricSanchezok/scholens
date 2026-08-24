"""
Celery tasks for Scholens jobs
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import psutil
import requests
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from scholens_ai import EMBEDDING_MODEL_REVISION, embed_text
from scholens_job_contracts import (
    PDF_TEXT_REPAIR_TASK_NAME,
    ZOTERO_CALLBACK_HTTP_TIMEOUT_SECONDS,
    PDFTextRepairTaskRequest,
    require_storage_delete_batch,
)

from src.audio import generate_audio
from src.celery_app import celery_app
from src.data_table_processor import construct_data_table
from src.pdf.models import (
    MinerUCredential,
    ParserConfigurationError,
    ParserError,
    ParserTransientError,
)
from src.pdf.pipeline import process_pdf_file
from src.reflow import generate_document_reflow
from src.s3_service import s3_service
from src.schemas import (
    AudioOverviewRequest,
    DataTableSchema,
    DataTableTaskRequest,
    DocumentReflowRequest,
    IntegrationUseEvent,
    JobIntegrationCredentialResponse,
    ResearchDataTableResult,
    ZoteroJobCredentialResponse,
)
from src.token_usage import collect_token_usage
from src.utils import time_it
from src.webhook_signing import CallbackPayloadTooLarge, post_signed_json
from src.zotero import (
    ZoteroJobCredential,
    ZoteroJobError,
    discard_unsubmitted_items,
    validate_zotero_callback_payload,
)
from src.zotero import (
    import_items as import_zotero_items,
)
from src.zotero import (
    sync_items as sync_zotero_items,
)

logger = logging.getLogger(__name__)

PDF_TASK_SOFT_TIME_LIMIT_SECONDS = 1200
PDF_TASK_TIME_LIMIT_SECONDS = 1260
JOB_HEARTBEAT_SECONDS = 30
JOB_PROGRESS_TIMEOUT_SECONDS = 5
JOB_CLAIM_MAX_RETRIES = 24
JOB_CLAIM_MAX_RETRY_DELAY_SECONDS = 300
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

PDF_STAGE_FAILURE_CODES = {
    "downloading": "paper_ingestion_downloading_failed",
    "parsing": "paper_ingestion_parsing_failed",
    "extracting_metadata": "paper_ingestion_metadata_failed",
    "indexing": "paper_ingestion_indexing_failed",
    "finalizing": "paper_ingestion_finalizing_failed",
}


def _pdf_failure_code(stage: str | None) -> str:
    return PDF_STAGE_FAILURE_CODES.get(
        stage or "downloading",
        "paper_ingestion_parsing_failed",
    )


def _normalize_pdf_progress(status: str, *, current: str) -> str:
    normalized = status.casefold()
    return next(
        (code for marker, code in PDF_PROGRESS_MARKERS if marker in normalized),
        current,
    )


class JobCancelled(Exception):
    """Raised at a cooperative boundary after Server cancels an ingestion."""


class ProgressReporter:
    def __init__(
        self,
        *,
        task_id: str,
        progress_url: str,
    ) -> None:
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
        logger.info(
            "job.status.updating",
            extra={"job_id": self._task_id, "status": status},
        )
        self._progress_code = _normalize_pdf_progress(
            status,
            current=self._progress_code,
        )
        self._post_progress()
        self.check_cancelled()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled("paper_ingestion_cancelled")

    @property
    def stage(self) -> str:
        return self._progress_code

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(JOB_HEARTBEAT_SECONDS):
            self._post_progress()

    def _post_progress(self) -> None:
        response: requests.Response | None = None
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
        finally:
            if response is not None:
                response.close()


def _deliver_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    timeout: float = 60,
) -> bool:
    response: requests.Response | None = None
    try:
        response = post_signed_json(webhook_url, payload, timeout=timeout)
        response.raise_for_status()
        logger.info("job.webhook.delivered", extra={"job_id": task_id})
        return True
    except requests.RequestException:
        logger.exception("job.webhook.delivery_failed", extra={"job_id": task_id})
        return False
    finally:
        if response is not None:
            response.close()


def _deliver_zotero_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
) -> bool:
    try:
        validate_zotero_callback_payload(payload)
    except ZoteroJobError:
        discard_unsubmitted_items(
            [
                item
                for field in ("items", "auto_imports")
                for item in payload.get(field) or []
                if isinstance(item, dict)
            ]
        )
        raise
    return _deliver_webhook(
        webhook_url,
        payload,
        task_id=task_id,
        timeout=ZOTERO_CALLBACK_HTTP_TIMEOUT_SECONDS,
    )


def _claim_job(claim_url: str | None, *, task_id: str) -> bool:
    if claim_url is None:
        return True
    response: requests.Response | None = None
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
    finally:
        if response is not None:
            response.close()


def _claim_job_with_retry(
    task: Task,
    claim_url: str | None,
    *,
    task_id: str,
) -> bool:
    """Claim durable Server state without acknowledging transient outages."""
    try:
        return _claim_job(claim_url, task_id=task_id)
    except requests.RequestException as exc:
        retries = int(getattr(task.request, "retries", 0) or 0)
        countdown = min(
            5 * (2 ** min(retries, 6)),
            JOB_CLAIM_MAX_RETRY_DELAY_SECONDS,
        )
        logger.warning(
            "job.claim.retrying",
            extra={
                "job_id": task_id,
                "retry_count": retries + 1,
                "retry_delay_seconds": countdown,
            },
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=JOB_CLAIM_MAX_RETRIES,
        ) from exc


def _log_data_table_progress(task_id: str, status: str) -> None:
    """Record progress without relying on a Celery result backend."""
    logger.info(
        "job.data_table.progress",
        extra={"job_id": task_id, "status": status},
    )


def _fetch_mineru_credential(credential_url: str) -> MinerUCredential:
    response: requests.Response | None = None
    try:
        response = post_signed_json(credential_url, {}, timeout=30)
    except requests.RequestException as exc:
        raise ParserTransientError(
            "Could not obtain the job-scoped MinerU credential",
            error_code="mineru_unavailable",
            phase="credential",
            exception_type=type(exc).__name__,
        ) from exc
    try:
        if response.status_code >= 400:
            try:
                code = str(response.json().get("code") or "")
            except (TypeError, ValueError):
                code = ""
            if code in {"mineru_credential_required", "integration_not_connected"}:
                raise ParserConfigurationError(
                    "A MinerU credential is required",
                    error_code="mineru_credential_required",
                    phase="credential",
                    http_status=response.status_code,
                )
            if code in {
                "mineru_credential_invalid",
                "integration_credentials_unreadable",
            }:
                raise ParserConfigurationError(
                    "The MinerU credential is invalid",
                    error_code="mineru_credential_invalid",
                    phase="credential",
                    http_status=response.status_code,
                )
            raise ParserTransientError(
                "Could not obtain the job-scoped MinerU credential",
                error_code="mineru_unavailable",
                phase="credential",
                http_status=response.status_code,
            )
        try:
            payload = JobIntegrationCredentialResponse.model_validate(response.json())
        except (TypeError, ValueError) as exc:
            raise ParserTransientError(
                "The job-scoped MinerU credential response is invalid",
                error_code="mineru_unavailable",
                phase="credential",
                exception_type=type(exc).__name__,
            ) from exc
        return MinerUCredential(
            token=payload.credential.get_secret_value(),
            revision=payload.credential_revision,
        )
    finally:
        response.close()


def _fetch_zotero_credential(credential_url: str) -> ZoteroJobCredential:
    response: requests.Response | None = None
    try:
        response = post_signed_json(credential_url, {}, timeout=30)
        response.raise_for_status()
        payload = ZoteroJobCredentialResponse.model_validate(response.json())
    except (requests.RequestException, TypeError, ValueError) as exc:
        raise ZoteroJobError("zotero_unavailable") from exc
    finally:
        if response is not None:
            response.close()
    return ZoteroJobCredential(
        user_id=payload.zotero_user_id,
        api_key=payload.credential.get_secret_value(),
        revision=payload.credential_revision,
    )


def _zotero_progress(progress_url: str, code: str) -> bool:
    response: requests.Response | None = None
    try:
        response = post_signed_json(
            progress_url,
            {"progress_code": code},
            timeout=JOB_PROGRESS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return bool(response.json().get("claimed"))
    except requests.RequestException:
        logger.warning("zotero.progress.delivery_failed", exc_info=True)
        return True
    finally:
        if response is not None:
            response.close()


@dataclass
class _MinerUCredentialSession:
    credential_url: str
    credential: MinerUCredential | None = None
    event: IntegrationUseEvent | None = None

    async def load(self) -> MinerUCredential:
        if self.credential is None:
            self.credential = await asyncio.to_thread(
                _fetch_mineru_credential,
                self.credential_url,
            )
        return self.credential

    def record(
        self,
        revision: str,
        outcome: Literal["verified", "invalid", "failed"],
        error_code: str | None,
    ) -> None:
        self.event = IntegrationUseEvent(
            credential_revision=revision,
            outcome=outcome,
            error_code=error_code,
        )

    def events(self) -> list[dict[str, Any]]:
        return [self.event.model_dump(mode="json")] if self.event is not None else []


def _process_pdf_task(
    task: Task,
    s3_object_key: str,
    webhook_url: str,
    progress_url: str,
    claim_url: str,
    credential_url: str,
    skip_metadata_extraction: bool = False,
    repair_revision: str | None = None,
) -> dict[str, Any]:
    """Run the shared claimed PDF workflow behind ingestion and repair tasks."""
    task_id = str(task.request.id)
    if not _claim_job_with_retry(task, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    usage_events: list[dict[str, Any]] = []
    progress: ProgressReporter | None = None
    mineru = _MinerUCredentialSession(credential_url)

    try:
        with ProgressReporter(
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
                        repair_revision=repair_revision,
                        mineru_credential_loader=mineru.load,
                        mineru_outcome_callback=mineru.record,
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
                "integration_events": mineru.events(),
            }

            webhook_delivered = _deliver_webhook(
                webhook_url,
                webhook_payload,
                task_id=task_id,
            )
            if not webhook_delivered:
                webhook_payload["webhook_error"] = "webhook_delivery_failed"

            logger.info("job.pdf_processing.completed", extra={"job_id": task_id})
            return webhook_payload

    except JobCancelled:
        logger.info("job.pdf_processing.cancelled", extra={"job_id": task_id})
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
            "integration_events": mineru.events(),
        }
        _deliver_webhook(webhook_url, timeout_payload, task_id=task_id)
        raise

    except Exception as exc:
        failure_stage = progress.stage if progress is not None else "downloading"
        explicit_error_code = getattr(exc, "error_code", None)
        failure_code = (
            explicit_error_code
            if isinstance(explicit_error_code, str)
            else _pdf_failure_code(failure_stage)
        )
        if mineru.credential is not None and mineru.event is None:
            mineru.record(
                mineru.credential.revision,
                "failed",
                failure_code,
            )
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
                "error": failure_code,
            },
            "error": failure_code,
            "usage_events": usage_events,
            "integration_events": mineru.events(),
        }
        if isinstance(exc, CallbackPayloadTooLarge):
            # The rejected success body can be large because of any one
            # producer-controlled projection. Keep the diagnostic callback
            # independently deliverable instead of replaying that projection.
            failure_payload["usage_events"] = []
            failure_payload["integration_events"] = []
        _deliver_webhook(webhook_url, failure_payload, task_id=task_id)
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
    credential_url: str,
    skip_metadata_extraction: bool = False,
    repair_revision: str | None = None,
) -> dict[str, Any]:
    """Process ordinary ingestion and already-accepted legacy repair jobs."""
    return _process_pdf_task(
        self,
        s3_object_key,
        webhook_url,
        progress_url,
        claim_url,
        credential_url,
        skip_metadata_extraction=skip_metadata_extraction,
        repair_revision=repair_revision,
    )


@celery_app.task(
    bind=True,
    name=PDF_TEXT_REPAIR_TASK_NAME,
    soft_time_limit=PDF_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=PDF_TASK_TIME_LIMIT_SECONDS,
)
def repair_pdf_text(
    self,
    job_id: str,
    document_id: str,
    s3_key: str,
    callback_url: str,
    claim_url: str,
    progress_url: str,
    mineru_credential_url: str,
    repair_revision: str,
    source_job_id: str,
    source_content_digest: str,
    repair_attempt: int,
) -> dict[str, Any]:
    """Consume one targeted, metadata-free canonical-text repair attempt."""
    request = PDFTextRepairTaskRequest(
        job_id=job_id,
        document_id=document_id,
        s3_key=s3_key,
        callback_url=callback_url,
        claim_url=claim_url,
        progress_url=progress_url,
        mineru_credential_url=mineru_credential_url,
        repair_revision=repair_revision,
        source_job_id=source_job_id,
        source_content_digest=source_content_digest,
        repair_attempt=repair_attempt,
    )
    if request.job_id != str(self.request.id):
        raise ValueError("pdf_text_repair_job_id_mismatch")
    return _process_pdf_task(
        self,
        request.s3_key,
        request.callback_url,
        request.progress_url,
        request.claim_url,
        request.mineru_credential_url,
        skip_metadata_extraction=True,
        repair_revision=request.repair_revision,
    )


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
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    usage_events: list[dict[str, Any]] = []

    def write_to_status(status: str) -> None:
        _log_data_table_progress(task_id, status)

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
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
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


@celery_app.task(
    bind=True,
    name="generate_document_reflow",
    soft_time_limit=1200,
    time_limit=1260,
)
def generate_document_reflow_task(
    self,
    request: dict[str, Any],
    webhook_url: str,
    claim_url: str | None = None,
    credential_url: str | None = None,
) -> dict[str, Any]:
    """Generate one lossless, idempotently addressed reading layout."""

    task_id = self.request.id
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    if credential_url is None:
        raise RuntimeError("document_reflow_credential_url_missing")
    usage_events: list[dict[str, Any]] = []
    mineru = _MinerUCredentialSession(credential_url)
    try:
        parsed = DocumentReflowRequest.model_validate(request)
        pdf_bytes = s3_service.download_file_to_bytes(parsed.pdf_s3_key)
        archive_bytes: bytes | None = None
        if parsed.mineru_archive_s3_key is not None:
            try:
                archive_bytes = s3_service.download_file_to_bytes(
                    parsed.mineru_archive_s3_key
                )
            except Exception:
                logger.warning(
                    "job.document_reflow.archive_download_failed",
                    exc_info=True,
                    extra={"job_id": task_id},
                )
        credential = asyncio.run(mineru.load())
        with collect_token_usage(task_id) as usage:
            usage_events = usage.events
            result = asyncio.run(
                generate_document_reflow(
                    document_id=parsed.document_id,
                    title=parsed.title,
                    pdf_bytes=pdf_bytes,
                    credential=credential,
                    archive_bytes=archive_bytes,
                    archive_parser_revision=parsed.mineru_archive_parser_revision,
                    outcome_callback=mineru.record,
                    write_asset=lambda data, key, content_type: (
                        s3_service.upload_bytes_to_key(data, key, content_type)
                    ),
                )
            )
        payload = {
            "task_id": task_id,
            "status": "completed",
            "result": result.model_dump(mode="json"),
            "usage_events": usage_events,
            "integration_events": mineru.events(),
        }
        if not _deliver_webhook(webhook_url, payload, task_id=task_id):
            payload["webhook_error"] = "webhook_delivery_failed"
        return payload
    except Exception as exc:
        logger.exception("job.document_reflow.failed", extra={"job_id": task_id})
        error_code = (
            exc.error_code if isinstance(exc, ParserError) else "document_reflow_failed"
        )
        if mineru.credential is not None and mineru.event is None:
            mineru.record(mineru.credential.revision, "failed", error_code)
        payload = {
            "task_id": task_id,
            "status": "failed",
            "result": None,
            "error": error_code,
            "usage_events": usage_events,
            "integration_events": mineru.events(),
        }
        _deliver_webhook(webhook_url, payload, task_id=task_id)
        raise


@celery_app.task(bind=True, name="postprocess_pdf")
def postprocess_pdf_task(
    self,
    callback_url: str,
    claim_url: str | None = None,
    semantic_text: str | None = None,
    semantic_source_digest: str | None = None,
) -> dict[str, Any]:
    """Trigger idempotent Server-side persistence work under a durable lease."""
    task_id = self.request.id
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    payload = {"task_id": task_id}
    if semantic_text and semantic_source_digest:
        try:
            embedding = embed_text(semantic_text, kind="passage")
            if embedding is not None:
                payload.update(
                    {
                        "embedding": embedding,
                        "embedding_model_revision": EMBEDDING_MODEL_REVISION,
                        "embedding_source_digest": semantic_source_digest,
                    }
                )
        except Exception:
            logger.exception(
                "job.pdf_postprocess.embedding_failed",
                extra={"job_id": task_id},
            )
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
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
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
    validated_keys = require_storage_delete_batch(object_keys)
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    failed = [key for key in validated_keys if not s3_service.delete_file(key)]
    if failed:
        logger.error(
            "storage.cleanup.failed",
            extra={"job_id": task_id, "failed_object_count": len(failed)},
        )
        raise RuntimeError("storage_delete_failed")
    payload = {"task_id": task_id, "deleted_count": len(validated_keys)}
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


@celery_app.task(bind=True, name="import_zotero_items")
def import_zotero_items_task(
    self,
    request: dict[str, Any],
    webhook_url: str,
    claim_url: str,
    credential_url: str,
    progress_url: str,
) -> dict[str, Any]:
    task_id = self.request.id
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    expected_revision = str(request.get("credential_revision") or "")
    try:
        credential = _fetch_zotero_credential(credential_url)
    except ZoteroJobError as exc:
        payload = {
            "task_id": task_id,
            "operation": "import",
            "credential_revision": expected_revision,
            "credential_outcome": "failed",
            "error_code": exc.code,
            "items": [],
        }
        if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
            raise RuntimeError("zotero_import_callback_failed")
        return payload
    if expected_revision != credential.revision:
        payload = {
            "task_id": task_id,
            "operation": "import",
            "credential_revision": expected_revision,
            "credential_outcome": "failed",
            "error_code": "zotero_credentials_rotated",
            "items": [],
        }
        if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
            raise RuntimeError("zotero_import_callback_failed")
        return payload
    if not _zotero_progress(progress_url, "fetching_library"):
        return {"task_id": task_id, "status": "cancelled"}
    try:
        item_keys = [str(value) for value in request.get("item_keys") or []]
        items, library_version = import_zotero_items(
            task_id=task_id,
            credential=credential,
            item_keys=item_keys,
            is_active=lambda: _zotero_progress(progress_url, "importing_papers"),
        )
        payload = {
            "task_id": task_id,
            "operation": "import",
            "credential_revision": credential.revision,
            "credential_outcome": "verified",
            "error_code": None,
            "items": items,
            "library_version": library_version,
        }
    except ZoteroJobError as exc:
        payload = {
            "task_id": task_id,
            "operation": "import",
            "credential_revision": credential.revision,
            "credential_outcome": "invalid" if exc.invalid_credential else "failed",
            "error_code": exc.code,
            "items": [],
        }
    if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
        raise RuntimeError("zotero_import_callback_failed")
    return payload


@celery_app.task(bind=True, name="sync_zotero")
def sync_zotero_task(
    self,
    request: dict[str, Any],
    webhook_url: str,
    claim_url: str,
    credential_url: str,
    progress_url: str,
) -> dict[str, Any]:
    task_id = self.request.id
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    expected_revision = str(request.get("credential_revision") or "")
    try:
        credential = _fetch_zotero_credential(credential_url)
    except ZoteroJobError as exc:
        payload = {
            "task_id": task_id,
            "operation": "sync",
            "credential_revision": expected_revision,
            "credential_outcome": "failed",
            "error_code": exc.code,
            "updates": [],
            "failures": [],
            "auto_imports": [],
        }
        if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
            raise RuntimeError("zotero_sync_callback_failed")
        return payload
    if expected_revision != credential.revision:
        payload = {
            "task_id": task_id,
            "operation": "sync",
            "credential_revision": expected_revision,
            "credential_outcome": "failed",
            "error_code": "zotero_credentials_rotated",
            "updates": [],
            "failures": [],
            "auto_imports": [],
        }
        if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
            raise RuntimeError("zotero_sync_callback_failed")
        return payload
    if not _zotero_progress(progress_url, "syncing_annotations"):
        return {"task_id": task_id, "status": "cancelled"}
    try:
        result = sync_zotero_items(
            task_id=task_id,
            credential=credential,
            targets=[
                value
                for value in request.get("targets") or []
                if isinstance(value, dict)
            ],
            auto_import_version=(
                int(request["auto_import_version"])
                if isinstance(request.get("auto_import_version"), int)
                and not isinstance(request.get("auto_import_version"), bool)
                else None
            ),
            auto_import_start=(
                int(request["auto_import_start"])
                if isinstance(request.get("auto_import_start"), int)
                and not isinstance(request.get("auto_import_start"), bool)
                and int(request["auto_import_start"]) >= 0
                else 0
            ),
            is_active=lambda: _zotero_progress(
                progress_url,
                "importing_papers",
            ),
        )
        payload = {
            "task_id": task_id,
            "operation": "sync",
            "credential_revision": credential.revision,
            "credential_outcome": "verified",
            "error_code": None,
            **result,
        }
    except ZoteroJobError as exc:
        payload = {
            "task_id": task_id,
            "operation": "sync",
            "credential_revision": credential.revision,
            "credential_outcome": "invalid" if exc.invalid_credential else "failed",
            "error_code": exc.code,
            "updates": [],
            "failures": [],
            "auto_imports": [],
        }
    if not _deliver_zotero_webhook(webhook_url, payload, task_id=task_id):
        raise RuntimeError("zotero_sync_callback_failed")
    return payload
