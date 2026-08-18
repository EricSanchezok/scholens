"""Orchestration for local-first PDF parsing with MinerU for scanned PDFs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from src.llm_client import llm_client
from src.pdf.local import (
    analyze_pdf,
    build_text_last_resort,
    extract_markdown_markitdown,
    extract_markdown_pymupdf4llm,
    is_scanned_candidate,
)
from src.pdf.mineru import MinerUClient, MinerUConfig
from src.pdf.models import (
    LocalPDFAnalysis,
    MinerUCredential,
    ParsedDocument,
    ParserConfigurationError,
    ParserContentError,
    ParserError,
    ParserSecurityError,
    ParserTransientError,
)
from src.s3_service import s3_service
from src.schemas import (
    PDFProcessingResult,
    PaperMetadataExtraction,
)

logger = logging.getLogger(__name__)


LOCAL_ENGINE_TIMEOUT_SECONDS = 120.0
MinerUCredentialLoader = Callable[[], Awaitable[MinerUCredential]]
MinerUOutcome = Callable[
    [str, Literal["verified", "invalid", "failed"], str | None], None
]


async def _upload_preview(
    analysis: LocalPDFAnalysis | BaseException,
    document_sha256: str,
) -> str | None:
    if isinstance(analysis, BaseException) or analysis.preview_bytes is None:
        return None
    try:
        object_key = _document_artifact_key(document_sha256, "preview.webp")
        await asyncio.to_thread(
            s3_service.upload_bytes_to_key,
            analysis.preview_bytes,
            object_key,
            "image/webp",
        )
        return object_key
    except Exception:
        logger.warning("job.pdf_preview.upload_failed", exc_info=True)
        return None


def _document_sha256_from_source_key(s3_object_key: str) -> str:
    match = re.fullmatch(r"documents/([0-9a-f]{64})/source\.pdf", s3_object_key)
    if match is None:
        raise ParserSecurityError(
            "Canonical source key is invalid",
            phase="source",
        )
    return match.group(1)


def _document_artifact_key(document_sha256: str, filename: str) -> str:
    return f"documents/{document_sha256}/{filename}"


async def _upload_markdown(document: ParsedDocument, document_sha256: str) -> str:
    markdown_key = _document_artifact_key(document_sha256, "canonical.md")
    await asyncio.to_thread(
        s3_service.upload_bytes_to_key,
        document.markdown.encode("utf-8"),
        markdown_key,
        "text/markdown; charset=utf-8",
    )
    return markdown_key


async def _upload_mineru_archive(
    document: ParsedDocument,
    document_sha256: str,
) -> str:
    if document.archive_bytes is None:
        raise ParserContentError(
            "MinerU full parse has no audit archive",
            phase="archive",
        )
    archive_key = _document_artifact_key(document_sha256, "mineru-result.zip")
    await asyncio.to_thread(
        s3_service.upload_bytes_to_key,
        document.archive_bytes,
        archive_key,
        "application/zip",
    )
    return archive_key


async def _parse_with_mineru(
    pdf_bytes: bytes,
    *,
    job_id: str,
    document_sha256: str,
    purpose: str,
    credential_loader: MinerUCredentialLoader | None,
    outcome_callback: MinerUOutcome | None,
    status_callback: Callable[[str], None],
) -> ParsedDocument:
    if credential_loader is None:
        raise ParserConfigurationError(
            "A MinerU credential is required",
            error_code="mineru_credential_required",
        )
    credential = await credential_loader()
    config = MinerUConfig.from_runtime(token=credential.token)
    checkpoint_scope = hashlib.sha256(
        f"{job_id}:{purpose}:{document_sha256}:{credential.revision}".encode()
    ).hexdigest()
    status_callback("Parsing scanned PDF with MinerU")
    client = MinerUClient(config)
    try:
        parsed = await client.parse_file(pdf_bytes, data_id=checkpoint_scope)
        if outcome_callback is not None:
            outcome_callback(credential.revision, "verified", None)
        try:
            await client.state_store.clear(checkpoint_scope)
        except ParserTransientError:
            logger.warning("job.mineru.checkpoint.clear_failed", exc_info=True)
        return parsed
    except ParserConfigurationError as exc:
        if outcome_callback is not None:
            outcome_callback(credential.revision, "invalid", exc.error_code)
        raise
    except ParserError as exc:
        if (
            isinstance(exc, ParserContentError)
            and exc.error_code == "pdf_content_insufficient"
        ):
            exc.error_code = "mineru_content_insufficient"
        if outcome_callback is not None:
            outcome_callback(credential.revision, "failed", exc.error_code)
        if not isinstance(exc, ParserTransientError):
            try:
                await client.state_store.clear(checkpoint_scope)
            except ParserTransientError:
                logger.warning("job.mineru.checkpoint.clear_failed", exc_info=True)
        raise
    finally:
        await client.close()


async def _parse_local_engines(
    pdf_path: str,
    analysis: LocalPDFAnalysis,
    *,
    status_callback: Callable[[str], None],
) -> ParsedDocument:
    """Try pymupdf4llm then MarkItDown, each under a bounded time budget."""
    status_callback("Parsing PDF with local pymupdf4llm")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                extract_markdown_pymupdf4llm,
                pdf_path,
                parser_version=analysis.parser_version,
            ),
            timeout=LOCAL_ENGINE_TIMEOUT_SECONDS,
        )
    except ParserContentError:
        pass
    except TimeoutError:
        logger.warning("job.pdf_parser.pymupdf4llm.timeout")

    status_callback("Parsing PDF with local MarkItDown")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                extract_markdown_markitdown,
                pdf_path,
                parser_version=analysis.parser_version,
                fallback_offsets=analysis.page_offset_map,
            ),
            timeout=LOCAL_ENGINE_TIMEOUT_SECONDS,
        )
    except ParserContentError:
        pass
    except TimeoutError:
        logger.warning("job.pdf_parser.markitdown.timeout")

    raise ParserContentError("Local PDF extraction failed")


async def process_pdf_file(
    pdf_bytes: bytes,
    s3_object_key: str,
    job_id: str,
    status_callback: Callable[[str], None],
    skip_metadata_extraction: bool = False,
    mineru_credential_loader: MinerUCredentialLoader | None = None,
    mineru_outcome_callback: MinerUOutcome | None = None,
) -> PDFProcessingResult:
    start_time = datetime.now(timezone.utc)
    document_sha256 = _document_sha256_from_source_key(s3_object_key)
    pdf_path: str | None = None

    try:
        analysis = await asyncio.to_thread(analyze_pdf, pdf_bytes)

        if is_scanned_candidate(analysis):
            # A scanned PDF has no usable text layer; only MinerU OCR can help.
            document = await _parse_with_mineru(
                pdf_bytes,
                job_id=job_id,
                document_sha256=document_sha256,
                purpose="pdf-ingestion",
                credential_loader=mineru_credential_loader,
                outcome_callback=mineru_outcome_callback,
                status_callback=status_callback,
            )
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(pdf_bytes)
                pdf_path = temp_file.name

            try:
                document = await _parse_local_engines(
                    pdf_path,
                    analysis,
                    status_callback=status_callback,
                )
            except ParserContentError:
                # Rescue path: MinerU OCR can recover misclassified or malformed
                # digital PDFs. Security failures must not be hidden; everything
                # else degrades to the deterministic per-page text last resort.
                try:
                    document = await _parse_with_mineru(
                        pdf_bytes,
                        job_id=job_id,
                        document_sha256=document_sha256,
                        purpose="pdf-ingestion",
                        credential_loader=mineru_credential_loader,
                        outcome_callback=mineru_outcome_callback,
                        status_callback=status_callback,
                    )
                except ParserSecurityError:
                    raise
                except ParserError:
                    logger.warning(
                        "job.pdf_parser.mineru_rescue_failed",
                        extra={"job_id": job_id},
                    )
                    document = build_text_last_resort(analysis)
                    status_callback("Using final text-only fallback")

        preview_object_key = await _upload_preview(analysis, document_sha256)
        markdown_key = await _upload_markdown(document, document_sha256)
        archive_key: str | None = None
        if document.archive_bytes is not None:
            archive_key = await _upload_mineru_archive(document, document_sha256)

        metadata: PaperMetadataExtraction | None = None
        if not skip_metadata_extraction:
            metadata = await llm_client.extract_paper_metadata(
                document.markdown,
                job_id=job_id,
                status_callback=status_callback,
            )
            if not metadata.title:
                raise ValueError("AI metadata extraction returned no title")

        return PDFProcessingResult(
            success=True,
            metadata=metadata,
            s3_object_key=s3_object_key,
            preview_s3_key=preview_object_key,
            parser_markdown_s3_key=markdown_key,
            parser_archive_s3_key=archive_key,
            parser_backend=document.backend.value,
            parser_quality=document.quality.value,
            parser_version=document.parser_version,
            parser_warning_code=document.warning_code,
            job_id=job_id,
            raw_content=document.markdown,
            page_offset_map=document.page_offset_map,
            duration=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    except ParserContentError as exc:
        logger.warning(
            "job.pdf_content.insufficient",
            extra={"job_id": job_id},
        )
        return PDFProcessingResult(
            success=False,
            error=exc.error_code,
            job_id=job_id,
            duration=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    finally:
        if pdf_path is not None:
            try:
                os.unlink(pdf_path)
            except OSError:
                logger.warning("job.pdf_temp.cleanup_failed")
