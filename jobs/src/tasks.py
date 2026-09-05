"""
Celery tasks for Scholens jobs
"""

import asyncio
import hashlib
import ipaddress
import logging
import os
import random
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import psutil
import httpx
import requests
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    MAX_PASSAGE_EMBEDDINGS,
    PASSAGE_EMBEDDING_BATCH_SIZE,
    PASSAGE_STRIDE_LINES,
    PassageEmbeddingRecord,
    build_document_passages,
    embed_text,
    encode_passage_embedding_artifact,
    try_local_embedder,
)
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
    JobSourceUrlResponse,
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


def _passage_embedding_artifact(
    *, task_id: str, parser_markdown_s3_key: str
) -> tuple[bytes, str, int] | None:
    raw_content = s3_service.download_file_to_bytes(parser_markdown_s3_key).decode(
        "utf-8"
    )
    line_count = raw_content.count("\n") + 1
    if (line_count + PASSAGE_STRIDE_LINES - 1) // PASSAGE_STRIDE_LINES > (
        MAX_PASSAGE_EMBEDDINGS
    ):
        return None
    passages_by_digest = {
        passage.source_digest: passage
        for passage in build_document_passages(raw_content)
        if passage.content.strip()
    }
    passages = tuple(passages_by_digest.values())
    if not passages or len(passages) > MAX_PASSAGE_EMBEDDINGS:
        return None
    embedder = try_local_embedder()
    if embedder is None:
        return None
    records: list[PassageEmbeddingRecord] = []
    for offset in range(0, len(passages), PASSAGE_EMBEDDING_BATCH_SIZE):
        batch = passages[offset : offset + PASSAGE_EMBEDDING_BATCH_SIZE]
        embeddings = embedder.embed_passages([passage.content for passage in batch])
        records.extend(
            PassageEmbeddingRecord(
                source_digest=passage.source_digest,
                embedding=tuple(embedding),
            )
            for passage, embedding in zip(batch, embeddings, strict=True)
        )
    artifact = encode_passage_embedding_artifact(
        model_revision=EMBEDDING_MODEL_REVISION,
        records=records,
    )
    key = f"jobs/pdf-postprocess/{task_id}/passage-embeddings-v1.bin"
    return artifact, key, len(records)


PDF_TASK_SOFT_TIME_LIMIT_SECONDS = 1200
PDF_TASK_TIME_LIMIT_SECONDS = 1260
JOB_HEARTBEAT_SECONDS = 30
JOB_PROGRESS_TIMEOUT_SECONDS = 5
JOB_CLAIM_MAX_RETRIES = 24
JOB_CLAIM_MAX_RETRY_DELAY_SECONDS = 300
SOURCE_MAX_BYTES = 30 * 1024 * 1024
SOURCE_MAX_REDIRECTS = 5
SOURCE_MAX_ATTEMPTS = 3
PDF_PROGRESS_MARKERS = (
    # Match terminal and specific stages before broad provider status text.
    # "PDF processing complete" intentionally contains "processing".
    ("complete", "finalizing"),
    ("finalizing", "finalizing"),
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


def _deliver_pdf_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    timeout: float = 60,
) -> bool:
    """Deliver the additive PDF result with a narrowly classified old-API retry."""

    response: requests.Response | None = None
    try:
        response = post_signed_json(webhook_url, payload, timeout=timeout)
        if _rejects_additive_pdf_page_count(response):
            response.close()
            response = None
            compatible_payload = _without_pdf_page_count(payload)
            logger.warning(
                "job.pdf_callback.page_count_compatibility_retry",
                extra={"compatibility_contract": "pdf_result_page_count"},
            )
            response = post_signed_json(
                webhook_url,
                compatible_payload,
                timeout=timeout,
            )
        response.raise_for_status()
        logger.info("job.webhook.delivered", extra={"job_id": task_id})
        return True
    except requests.RequestException:
        logger.exception("job.webhook.delivery_failed", extra={"job_id": task_id})
        return False
    finally:
        if response is not None:
            response.close()


def _rejects_additive_pdf_page_count(response: requests.Response) -> bool:
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or body.get("code") != "request_validation_failed":
        return False
    details = body.get("details")
    if not isinstance(details, dict):
        return False
    errors = details.get("errors")
    if not isinstance(errors, list) or not errors:
        return False
    for error in errors:
        if not isinstance(error, dict):
            return False
        location = error.get("location")
        if not isinstance(location, (list, tuple)):
            return False
        if tuple(location) != ("body", "result", "page_count"):
            return False
        if error.get("type") not in {"extra_forbidden", "value_error.extra"}:
            return False
    return True


def _without_pdf_page_count(payload: dict[str, Any]) -> dict[str, Any]:
    compatible = dict(payload)
    result = payload.get("result")
    if isinstance(result, dict):
        compatible["result"] = {
            key: value for key, value in result.items() if key != "page_count"
        }
    return compatible


def _deliver_pdf_postprocess_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    timeout: float = 60,
) -> bool:
    """Retry an old Server once without the additive passage artifact."""

    response: requests.Response | None = None
    try:
        response = post_signed_json(webhook_url, payload, timeout=timeout)
        if _rejects_additive_passage_artifact(response):
            response.close()
            response = None
            logger.warning(
                "job.pdf_postprocess.passage_artifact_compatibility_retry",
                extra={"compatibility_contract": "passage_embedding_artifact"},
            )
            response = post_signed_json(
                webhook_url,
                {
                    key: value
                    for key, value in payload.items()
                    if key != "passage_embedding_artifact"
                },
                timeout=timeout,
            )
        response.raise_for_status()
        logger.info("job.webhook.delivered", extra={"job_id": task_id})
        return True
    except requests.RequestException:
        logger.exception("job.webhook.delivery_failed", extra={"job_id": task_id})
        return False
    finally:
        if response is not None:
            response.close()


def _rejects_additive_passage_artifact(response: requests.Response) -> bool:
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or body.get("code") != "request_validation_failed":
        return False
    details = body.get("details")
    errors = details.get("errors") if isinstance(details, dict) else None
    if not isinstance(errors, list) or not errors:
        return False
    return all(
        isinstance(error, dict)
        and tuple(error.get("location", ())) == ("body", "passage_embedding_artifact")
        and error.get("type") in {"extra_forbidden", "value_error.extra"}
        for error in errors
    )


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


class SourceDownloadError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        retry_after: float = 0.0,
    ) -> None:
        super().__init__(code)
        self.error_code = code
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


def _response_error_code(response: requests.Response, default: str) -> str:
    try:
        payload = response.json()
    except (requests.JSONDecodeError, TypeError, ValueError):
        return default
    if not isinstance(payload, dict):
        return default
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return str(payload.get("code") or default)


def _resolve_source_url(url: str) -> str:
    response: requests.Response | None = None
    try:
        response = post_signed_json(url, {}, timeout=30)
    except requests.RequestException as exc:
        raise SourceDownloadError(
            "paper_source_resolution_unavailable",
            retryable=True,
        ) from exc
    try:
        status = response.status_code
        if status >= 400:
            try:
                retry_after = float(response.headers.get("Retry-After", "0") or 0)
            except ValueError:
                retry_after = 0.0
            raise SourceDownloadError(
                _response_error_code(response, "paper_source_resolution_failed"),
                status=status,
                retryable=status in {408, 425, 429} or status >= 500,
                retry_after=max(0.0, min(retry_after, 60.0)),
            )
        try:
            payload = JobSourceUrlResponse.model_validate(response.json())
        except (TypeError, ValueError) as exc:
            raise SourceDownloadError(
                "paper_source_resolution_invalid",
                status=status,
                retryable=True,
            ) from exc
        return payload.resolved_url
    finally:
        response.close()


def _source_host(url: str) -> str | None:
    try:
        return httpx.URL(url).host
    except httpx.InvalidURL:
        return None


def _validate_source_url(url: str) -> None:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise SourceDownloadError("paper_source_unsafe_address") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise SourceDownloadError("paper_source_unsafe_address")
    if parsed.username or parsed.password:
        raise SourceDownloadError("paper_source_unsafe_address")
    try:
        addresses = socket.getaddrinfo(
            parsed.host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise SourceDownloadError("paper_source_dns_failed", retryable=True) from exc
    try:
        unsafe_address = not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        )
    except (IndexError, KeyError, ValueError) as exc:
        raise SourceDownloadError("paper_source_unsafe_address") from exc
    if unsafe_address:
        raise SourceDownloadError("paper_source_unsafe_address")


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("retry-after")
    if value is None:
        return 0.0
    try:
        return max(0.0, min(float(value), 60.0))
    except ValueError:
        return 0.0


def _stream_url_to_file(
    url: str,
    destination: str,
    *,
    job_id: str,
    attempt: int,
) -> tuple[str, int]:
    current = url
    with httpx.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(30.0),
    ) as client:
        for redirect_count in range(SOURCE_MAX_REDIRECTS + 1):
            _validate_source_url(current)
            try:
                response_context = client.stream(
                    "GET",
                    current,
                    headers={
                        "Accept": "application/pdf",
                        "Accept-Encoding": "identity",
                    },
                )
                with response_context as response:
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count >= SOURCE_MAX_REDIRECTS:
                            raise SourceDownloadError(
                                "paper_source_redirect_invalid", status=status
                            )
                        current = str(httpx.URL(current).join(location))
                        continue
                    if status in {408, 425, 429} or status >= 500:
                        raise SourceDownloadError(
                            "paper_source_retryable",
                            status=status,
                            retryable=True,
                            retry_after=_retry_after(response),
                        )
                    if status >= 400:
                        raise SourceDownloadError(
                            "paper_source_http_error", status=status
                        )
                    network_stream = response.extensions.get("network_stream")
                    if network_stream is None:
                        raise SourceDownloadError(
                            "paper_source_unsafe_address", status=status
                        )
                    peer = network_stream.get_extra_info("server_addr")
                    try:
                        unsafe_peer = (
                            not isinstance(peer, tuple)
                            or not peer
                            or not ipaddress.ip_address(str(peer[0])).is_global
                        )
                    except (IndexError, ValueError) as exc:
                        raise SourceDownloadError(
                            "paper_source_unsafe_address", status=status
                        ) from exc
                    if unsafe_peer:
                        raise SourceDownloadError(
                            "paper_source_unsafe_address", status=status
                        )
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .casefold()
                    )
                    if content_type and content_type not in {
                        "application/pdf",
                        "application/octet-stream",
                    }:
                        raise SourceDownloadError("invalid_pdf", status=status)
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            declared_size = int(declared)
                        except ValueError as exc:
                            raise SourceDownloadError(
                                "paper_source_content_length_invalid", status=status
                            ) from exc
                        if declared_size > SOURCE_MAX_BYTES:
                            raise SourceDownloadError("upload_too_large", status=status)
                    hasher = hashlib.sha256()
                    written = 0
                    with open(destination, "wb") as output:
                        for chunk in response.iter_raw(1024 * 1024):
                            written += len(chunk)
                            if written > SOURCE_MAX_BYTES:
                                raise SourceDownloadError(
                                    "upload_too_large", status=status
                                )
                            output.write(chunk)
                            hasher.update(chunk)
                    if written < 1024:
                        raise SourceDownloadError("invalid_pdf", status=status)
                    with open(destination, "rb") as header:
                        if header.read(5) != b"%PDF-":
                            raise SourceDownloadError("invalid_pdf", status=status)
                    logger.info(
                        "paper.source.downloaded",
                        extra={
                            "job_id": job_id,
                            "attempt": attempt,
                            "http_status": status,
                            "content_length": written,
                            "host": httpx.URL(current).host,
                        },
                    )
                    return hasher.hexdigest(), written
            except httpx.TimeoutException as exc:
                raise SourceDownloadError(
                    "paper_source_timeout", retryable=True
                ) from exc
            except httpx.RequestError as exc:
                raise SourceDownloadError(
                    "paper_source_network_error", retryable=True
                ) from exc
    raise SourceDownloadError("paper_source_redirect_invalid")


def _deliver_source_ready(
    url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = post_signed_json(url, payload, timeout=60)
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise SourceDownloadError(
            "source_ready_unavailable",
            status=status if isinstance(status, int) else None,
            retryable=status is None or status == 429 or status >= 500,
        ) from exc
    try:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = response.status_code
            try:
                retry_after = float(response.headers.get("Retry-After", "0") or 0)
            except ValueError:
                retry_after = 0.0
            raise SourceDownloadError(
                "source_ready_unavailable",
                status=status,
                retryable=status == 429 or status >= 500,
                retry_after=max(0.0, min(retry_after, 60.0)),
            ) from exc
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("source_ready_response_invalid")
        return body
    finally:
        response.close()


def _post_source_progress(progress_url: str, *, task_id: str) -> None:
    response: requests.Response | None = None
    try:
        response = post_signed_json(
            progress_url,
            {"progress_code": "downloading"},
            timeout=JOB_PROGRESS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("paper.source.progress_failed", extra={"job_id": task_id})
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
    claim_url: str | None,
    credential_url: str,
    skip_metadata_extraction: bool = False,
    repair_revision: str | None = None,
    local_pdf_path: str | None = None,
) -> dict[str, Any]:
    """Run the shared claimed PDF workflow behind ingestion and repair tasks."""
    task_id = str(task.request.id)
    if not _claim_job_with_retry(task, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    usage_events: list[dict[str, Any]] = []
    progress: ProgressReporter | None = None
    mineru = _MinerUCredentialSession(credential_url)
    pdf_temp_path: str | None = None

    try:
        with ProgressReporter(
            task_id=task_id,
            progress_url=progress_url,
        ) as progress:
            logger.info("job.pdf_processing.started", extra={"job_id": task_id})
            progress.update("Downloading PDF from S3")

            if local_pdf_path is None:
                pdf_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                pdf_temp.close()
                pdf_temp_path = pdf_temp.name

                async def download_with_timer():
                    async with time_it("Downloading PDF from S3", job_id=task_id):
                        return s3_service.download_file_to_path(
                            s3_object_key, pdf_temp.name
                        )

                downloaded_size = asyncio.run(download_with_timer())
            else:
                pdf_temp_path = local_pdf_path
                downloaded_size = os.path.getsize(local_pdf_path)
            logger.info(
                "job.pdf_processing.source_downloaded",
                extra={"job_id": task_id, "content_length": downloaded_size},
            )
            progress.check_cancelled()

            progress.update("Processing PDF file")

            with collect_token_usage(task_id) as usage:
                usage_events = usage.events
                result = asyncio.run(
                    process_pdf_file(
                        None,
                        s3_object_key,
                        task_id,
                        status_callback=progress.update,
                        skip_metadata_extraction=skip_metadata_extraction,
                        repair_revision=repair_revision,
                        mineru_credential_loader=mineru.load,
                        mineru_outcome_callback=mineru.record,
                        pdf_path=pdf_temp_path,
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

            webhook_delivered = _deliver_pdf_webhook(
                webhook_url,
                webhook_payload,
                task_id=task_id,
            )
            if not webhook_delivered:
                webhook_payload["webhook_error"] = "webhook_delivery_failed"

            logger.info("job.pdf_processing.completed", extra={"job_id": task_id})
            _cleanup_pdf_temp(pdf_temp_path)
            return webhook_payload

    except JobCancelled:
        logger.info("job.pdf_processing.cancelled", extra={"job_id": task_id})
        _cleanup_pdf_temp(pdf_temp_path)
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
        _cleanup_pdf_temp(pdf_temp_path)
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
        _cleanup_pdf_temp(pdf_temp_path)
        raise


def _cleanup_pdf_temp(path: str | None) -> None:
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        logger.warning("job.pdf_temp.cleanup_failed")


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
    name="ingest_source_and_process",
    soft_time_limit=PDF_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=PDF_TASK_TIME_LIMIT_SECONDS,
)
def ingest_source_and_process(
    self,
    source: dict[str, Any],
    staging_object_key: str,
    source_ready_url: str,
    webhook_url: str,
    progress_url: str,
    claim_url: str,
    credential_url: str,
    filename: str | None = None,
    source_resolve_url: str | None = None,
) -> dict[str, Any]:
    """Materialize a URL/upload source and process its local file in one task."""
    task_id = str(self.request.id)
    if not _claim_job_with_retry(self, claim_url, task_id=task_id):
        return {"task_id": task_id, "status": "duplicate"}
    _post_source_progress(progress_url, task_id=task_id)
    source_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    source_path.close()
    processing_started = False
    try:
        staging_exists = s3_service.object_exists(staging_object_key)
        if staging_exists:
            try:
                s3_service.download_file_to_path(
                    staging_object_key, source_path.name, max_bytes=SOURCE_MAX_BYTES
                )
            except ValueError as exc:
                raise SourceDownloadError("upload_too_large") from exc
            with open(source_path.name, "rb") as existing:
                prefix = existing.read(5)
            if prefix != b"%PDF-":
                raise SourceDownloadError("invalid_pdf")
            hasher = hashlib.sha256()
            size = 0
            with open(source_path.name, "rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    hasher.update(chunk)
                    size += len(chunk)
            digest = hasher.hexdigest()
            logger.info(
                "paper.source.staging_reused",
                extra={"job_id": task_id, "content_length": size},
            )
        else:
            object_key = source.get("canonical_object_key") or source.get(
                "upload_object_key"
            )
            if isinstance(object_key, str) and object_key:
                try:
                    size = s3_service.download_file_to_path(
                        object_key,
                        source_path.name,
                        max_bytes=SOURCE_MAX_BYTES,
                    )
                except ValueError as exc:
                    raise SourceDownloadError("upload_too_large") from exc
                if size > SOURCE_MAX_BYTES:
                    raise SourceDownloadError("upload_too_large")
                hasher = hashlib.sha256()
                with open(source_path.name, "rb") as uploaded:
                    for chunk in iter(lambda: uploaded.read(1024 * 1024), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
                with open(source_path.name, "rb") as uploaded:
                    if uploaded.read(5) != b"%PDF-":
                        raise SourceDownloadError("invalid_pdf")
            else:
                resolved_url = source.get("resolved_url")
                if not isinstance(resolved_url, str):
                    resolved_url = ""
                if not resolved_url and not source_resolve_url:
                    raise SourceDownloadError("paper_source_pdf_unavailable")
                last_error: SourceDownloadError | None = None
                for attempt in range(1, SOURCE_MAX_ATTEMPTS + 1):
                    try:
                        if not resolved_url:
                            assert source_resolve_url is not None
                            resolved_url = _resolve_source_url(source_resolve_url)
                        digest, size = _stream_url_to_file(
                            resolved_url,
                            source_path.name,
                            job_id=task_id,
                            attempt=attempt,
                        )
                        last_error = None
                        break
                    except SourceDownloadError as error:
                        last_error = error
                        logger.warning(
                            "paper.source.download_failed",
                            extra={
                                "job_id": task_id,
                                "attempt": attempt,
                                "http_status": error.status,
                                "retry_after": error.retry_after,
                                "host": _source_host(resolved_url),
                            },
                        )
                        if not error.retryable or attempt >= SOURCE_MAX_ATTEMPTS:
                            error.retryable = False
                            raise
                        time.sleep(
                            error.retry_after
                            or min(2 ** (attempt - 1), 30) + random.random()
                        )
                if last_error is not None:
                    raise last_error
        expected_sha256 = source.get("expected_sha256")
        if isinstance(expected_sha256, str) and digest != expected_sha256:
            raise SourceDownloadError("source_checksum_mismatch")
        if size > SOURCE_MAX_BYTES:
            raise SourceDownloadError("upload_too_large")
        if not staging_exists:
            s3_service.upload_file(
                source_path.name,
                staging_object_key,
                "application/pdf",
                checksum_sha256=digest,
            )

        ready = _deliver_source_ready(
            source_ready_url,
            {
                "task_id": task_id,
                "source_sha256": digest,
                "size_bytes": size,
                "staging_object_key": staging_object_key,
                "filename": filename,
                "attempt": int(getattr(self.request, "retries", 0) or 0) + 1,
            },
        )
        canonical_key = ready.get("canonical_object_key")
        if not isinstance(canonical_key, str) or not canonical_key:
            raise RuntimeError("source_ready_response_invalid")
        if not bool(ready.get("process_required", True)):
            s3_service.delete_file(staging_object_key)
            return {"task_id": task_id, "status": "completed", "reused": True}
        processing_started = True
        result = _process_pdf_task(
            self,
            canonical_key,
            webhook_url,
            progress_url,
            claim_url=None,
            credential_url=credential_url,
            local_pdf_path=source_path.name,
        )
        s3_service.delete_file(staging_object_key)
        return result
    except SourceDownloadError as error:
        if error.retryable:
            raise self.retry(
                exc=error,
                countdown=error.retry_after or 15,
                max_retries=SOURCE_MAX_ATTEMPTS,
            ) from error
        s3_service.delete_file(staging_object_key)
        fail_url = claim_url.rsplit("/", 1)[0] + "/fail"
        _deliver_webhook(
            fail_url,
            {"task_id": task_id, "error_code": error.error_code},
            task_id=task_id,
        )
        raise
    except Exception:
        if not processing_started:
            fail_url = claim_url.rsplit("/", 1)[0] + "/fail"
            _deliver_webhook(
                fail_url,
                {
                    "task_id": task_id,
                    "error_code": "paper_source_materialization_failed",
                },
                task_id=task_id,
            )
        raise
    finally:
        try:
            os.unlink(source_path.name)
        except OSError:
            logger.warning("job.source_temp.cleanup_failed", extra={"job_id": task_id})


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
    parser_markdown_s3_key: str | None = None,
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
    if parser_markdown_s3_key:
        try:
            built = _passage_embedding_artifact(
                task_id=task_id,
                parser_markdown_s3_key=parser_markdown_s3_key,
            )
            if built is not None:
                artifact, storage_key, passage_count = built
                digest = hashlib.sha256(artifact).hexdigest()
                s3_service.upload_bytes_to_key(
                    artifact,
                    storage_key,
                    "application/vnd.scholens.passage-embeddings-v1",
                )
                payload["passage_embedding_artifact"] = {
                    "storage_key": storage_key,
                    "sha256": digest,
                    "model_revision": EMBEDDING_MODEL_REVISION,
                    "dimension": 384,
                    "passage_count": passage_count,
                    "byte_size": len(artifact),
                }
        except Exception:
            logger.exception(
                "job.pdf_postprocess.passage_embedding_failed",
                extra={"job_id": task_id},
            )
    if not _deliver_pdf_postprocess_webhook(
        callback_url,
        payload,
        task_id=task_id,
    ):
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
