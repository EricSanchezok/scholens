"""Optional paid enrichment after canonical content is already readable."""

import asyncio
import hashlib
import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from scholens_job_contracts import MAX_PDF_CALLBACK_RAW_CONTENT_BYTES

from src.deepseek_credentials import DeepSeekCredentialRequired, deepseek_job_context
from src.execution_delivery import (
    DeliveryUnavailable,
    ExecutionLost,
    FencedExecution,
    ResultStorage,
)
from src.llm_client import llm_client
from src.token_usage import collect_token_usage

logger = logging.getLogger(__name__)


def enrich_document(
    execution: FencedExecution,
    *,
    storage: ResultStorage,
    callback_url: str,
    parser_markdown_s3_key: str,
    content_digest: str,
) -> dict[str, Any]:
    try:
        try:
            source = storage.download_bounded_bytes(
                parser_markdown_s3_key, max_bytes=MAX_PDF_CALLBACK_RAW_CONTENT_BYTES
            ).decode("utf-8")
        except (BotoCoreError, ClientError) as exc:
            raise DeliveryUnavailable("document_enrichment_source_unavailable") from exc
        if hashlib.sha256(source.encode()).hexdigest() != content_digest:
            execution.fail("document_stage_source_changed")
            return {"status": "failed"}
        execution.report("extracting_metadata")
        with (
            deepseek_job_context(callback_url),
            collect_token_usage(execution.job_id) as usage,
        ):
            metadata = asyncio.run(
                llm_client.extract_paper_metadata(
                    source,
                    execution.job_id,
                    before_provider=execution.begin_external_effect,
                )
            )
        execution.complete(
            {
                "task_id": execution.job_id,
                "content_digest": content_digest,
                "metadata": metadata.model_dump(mode="json"),
                "usage_events": usage.events,
            }
        )
        return {"status": "completed"}
    except (DeliveryUnavailable, ExecutionLost):
        raise
    except Exception as exc:
        code = (
            "deepseek_credential_required"
            if isinstance(exc, DeepSeekCredentialRequired)
            else "document_enrichment_failed"
        )
        logger.warning(
            "job.document_enrichment.failed",
            extra={
                "job_id": execution.job_id,
                "error_code": code,
                "error_class": type(exc).__name__,
            },
        )
        execution.fail(code)
        return {"status": "failed"}
