"""Unicode PDF text-repair callback policy and persistence orchestration."""

import hashlib
import logging
import re
import uuid
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone

from scholens_job_contracts import (
    PDF_TEXT_REPAIR_MAX_ATTEMPTS,
    UNICODE_REPLACEMENT_WARNING_CODE,
)
from scholens_observability import add_counter
from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session, load_only

from app.bootstrap.adapters.document_job_callback_support import (
    complete_pdf_job as _complete_pdf_job,
)
from app.bootstrap.adapters.document_job_callback_support import (
    document_change as _document_change,
)
from app.bootstrap.adapters.document_job_callback_support import (
    safe_pdf_failure_code as _safe_pdf_failure_code,
)
from app.bootstrap.adapters.document_repair_artifacts import (
    UNICODE_REPAIR_KIND,
    unicode_repair_artifact_keys,
)
from app.bootstrap.adapters.storage_cleanup import schedule_storage_deletion
from app.database.models import (
    AnnotationThread,
    Document,
    DocumentProcessingStatus,
    DurableJob,
    ResearchItem,
)
from app.modules.jobs.application.callbacks import (
    JobHandlerResult,
    JobPostCommitAction,
)
from app.modules.jobs.application.contracts import PDFProcessingResult
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.application.actions import DOCUMENT_PROCESSING_COMPLETED
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.application.data_repair import (
    UNICODE_REPLACEMENT_REPAIR_REVISION,
)
from app.modules.papers.domain.content_repair import assess_canonical_text_repair
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from app.modules.reflows.infrastructure.models import DocumentReflow
from app.shared.domain import JsonValue

# Preserve the established callback logger identity after extracting this policy.
logger = logging.getLogger("app.bootstrap.adapters.document_job_callbacks")

UNICODE_REPAIR_CONTRACT_ERROR = "pdf_unicode_repair_contract_invalid"
UNICODE_REPAIR_OBSOLETE_ERROR = "pdf_unicode_repair_obsolete"
UNICODE_REPAIR_SUPPORTED_REVISIONS = frozenset({UNICODE_REPLACEMENT_REPAIR_REVISION})
REFLOW_CANONICAL_REVISION_CHANGED = "document_reflow_source_revision_changed"
UNICODE_REPAIR_MAX_CANDIDATE_UTF8_BYTES = 40 * 1024 * 1024
UNICODE_REPAIR_MAX_REANCHOR_THREADS = 256
UNICODE_REPAIR_MAX_REANCHOR_QUOTE_UTF8_BYTES = 1024 * 1024
UNICODE_REPAIR_MAX_REANCHOR_POSITION_UTF8_BYTES = 1024 * 1024
UNICODE_REPAIR_MAX_REANCHOR_SCAN_CHARACTERS = 256 * 1024 * 1024

_ParsedTextReanchor = tuple[AnnotationThread, int, int, int | None]


@dataclass(frozen=True, slots=True)
class _RepairContext:
    source_job_id: uuid.UUID
    current_job_id: uuid.UUID
    document_id: uuid.UUID
    document: Document
    current_content: str
    candidate_content: str


@dataclass(frozen=True, slots=True)
class _RepairPlan:
    applied: bool
    reason: str
    current_replacement_count: int
    candidate_replacement_count: int
    reanchors: tuple[_ParsedTextReanchor, ...]


def _unicode_repair_source_job_id(job: DurableJob) -> uuid.UUID | None:
    payload = job.payload
    if payload.get("repair_kind") != UNICODE_REPAIR_KIND:
        return None
    try:
        return uuid.UUID(str(payload.get("repair_source_job_id")))
    except (TypeError, ValueError):
        return None


def unicode_repair_contract_issue(
    *,
    durable_job: DurableJob,
    result: PDFProcessingResult,
) -> str | None:
    """Return one bounded reason when a repair callback violates its envelope."""

    job_id = durable_job.id
    document_id = durable_job.document_id
    payload = durable_job.payload
    revision = payload.get("repair_revision")
    source_sha256 = payload.get("content_sha256")
    source_content_digest = payload.get("repair_source_content_digest")
    repair_attempt = payload.get("repair_attempt")
    if not isinstance(job_id, uuid.UUID) or not isinstance(document_id, uuid.UUID):
        return "scope_invalid"
    if (
        not isinstance(revision, str)
        or revision not in UNICODE_REPAIR_SUPPORTED_REVISIONS
    ):
        return "revision_unsupported"
    source_job_id = _unicode_repair_source_job_id(durable_job)
    if (
        not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or not isinstance(source_content_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_content_digest) is None
        or source_job_id is None
        or source_job_id == job_id
        or payload.get("job_visibility") != "maintenance"
        or isinstance(repair_attempt, bool)
        or not isinstance(repair_attempt, int)
        or not 1 <= repair_attempt <= PDF_TEXT_REPAIR_MAX_ATTEMPTS
    ):
        return "source_identity_invalid"
    try:
        result_job_id = uuid.UUID(result.job_id)
    except (TypeError, ValueError):
        return "result_job_id_invalid"
    if result_job_id != job_id:
        return "result_job_id_mismatch"
    if not result.success:
        return None
    if (
        result.raw_content is not None
        and len(result.raw_content.encode("utf-8"))
        > UNICODE_REPAIR_MAX_CANDIDATE_UTF8_BYTES
    ):
        return "candidate_content_too_large"

    prefix = f"documents/{source_sha256}/repairs/{revision}/{job_id}/"
    if result.parser_markdown_s3_key != f"{prefix}canonical.md":
        return "markdown_artifact_scope_invalid"
    if (
        result.parser_archive_s3_key is not None
        and result.parser_archive_s3_key != f"{prefix}mineru-result.zip"
    ):
        return "archive_artifact_scope_invalid"
    return None


def _repair_terminal_result(*, outcome: str) -> dict[str, JsonValue]:
    return {
        "repair_applied": False,
        "repair_outcome": outcome,
    }


def _schedule_repair_artifact_deletion(
    *,
    db: Session,
    durable_job: DurableJob,
    suffix: str,
) -> None:
    keys = unicode_repair_artifact_keys(
        job_id=durable_job.id,
        payload=durable_job.payload,
    )
    if not keys:
        return
    schedule_storage_deletion(
        db,
        object_keys=keys,
        idempotency_key=f"unicode-repair:{durable_job.id}:{suffix}",
        origin_operation_id=durable_job.origin_operation_id,
        correlation_id=durable_job.correlation_id,
    )


def schedule_terminal_unicode_repair_cleanup(
    *,
    db: Session,
    durable_job: DurableJob,
) -> None:
    """Delete late worker artifacts for an already failed/cancelled repair."""

    _schedule_repair_artifact_deletion(
        db=db,
        durable_job=durable_job,
        suffix=f"terminal-{durable_job.status}",
    )


def _bounded_repair_result(
    *,
    result: PDFProcessingResult,
    plan: _RepairPlan,
) -> dict[str, JsonValue]:
    candidate = result.raw_content or ""
    return {
        "success": result.success,
        "job_id": result.job_id,
        "repair_applied": plan.applied,
        "repair_outcome": "applied" if plan.applied else plan.reason,
        "current_replacement_count": plan.current_replacement_count,
        "candidate_replacement_count": plan.candidate_replacement_count,
        "candidate_content_sha256": hashlib.sha256(
            candidate.encode("utf-8")
        ).hexdigest(),
        "candidate_character_count": len(candidate),
        "candidate_page_count": len(result.page_offset_map or {}),
        "parser_markdown_s3_key": result.parser_markdown_s3_key,
        "parser_archive_s3_key": result.parser_archive_s3_key,
        "parser_backend": result.parser_backend,
        "parser_quality": result.parser_quality,
        "parser_version": result.parser_version,
        "parser_warning_code": result.parser_warning_code,
        "duration": result.duration,
    }


def _record_unicode_repair_outcome(*, outcome: str) -> None:
    # Every caller supplies one of the closed, low-cardinality outcomes in this
    # module. Never attach document/job identifiers to metric attributes.
    add_counter(
        "scholens.documents.pdf_unicode_repairs",
        attributes={"outcome": outcome},
    )


def _restore_failed_unicode_repair(
    *,
    db: Session,
    durable_job: DurableJob,
) -> None:
    source_job_id = _unicode_repair_source_job_id(durable_job)
    document_id = durable_job.document_id
    current_job_id = durable_job.id
    if source_job_id is None or document_id is None or current_job_id is None:
        return
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if (
        document is not None
        and document.processing_status == DocumentProcessingStatus.COMPLETED.value
        and document.processing_job_id == current_job_id
    ):
        document.processing_job_id = source_job_id
        document.parser_quality = "text_only"
        document.parser_warning_code = UNICODE_REPLACEMENT_WARNING_CODE


def _terminate_rejected_unicode_repair(
    *,
    db: Session,
    durable_job: DurableJob,
    outcome: str,
    post_commit: tuple[JobPostCommitAction, ...],
    error_code: str | None = None,
) -> JobHandlerResult:
    """Make a rejected repair terminal so an obsolete callback is not retried."""

    job_id = durable_job.id
    if not isinstance(job_id, uuid.UUID):
        # A persisted DurableJob cannot reach this state; unlike source drift,
        # this is a database/programming invariant rather than an obsolete job.
        raise RuntimeError(UNICODE_REPAIR_CONTRACT_ERROR)
    result = _repair_terminal_result(outcome=outcome)
    if error_code is None:
        _job, changed = job_repository.complete(db, job_id=job_id, result=result)
        terminal_status = "completed"
    else:
        _job, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=error_code,
            result=result,
        )
        terminal_status = "failed"
    _restore_failed_unicode_repair(db=db, durable_job=durable_job)
    _schedule_repair_artifact_deletion(
        db=db,
        durable_job=durable_job,
        suffix="rejected",
    )
    _record_unicode_repair_outcome(outcome=outcome)
    logger.warning(
        "document.pdf_unicode_repair.rejected",
        extra={
            "job_id": str(job_id),
            "document_id": str(durable_job.document_id),
            "repair_outcome": outcome,
            "terminal_status": terminal_status,
            "job_changed": changed,
        },
    )
    return JobHandlerResult(
        value={
            "status": "webhook processed - unicode repair rejected",
            "repair_applied": False,
            "repair_reason": outcome,
        },
        post_commit=post_commit,
    )


def failed_unicode_repair_result(
    *,
    db: Session,
    durable_job: DurableJob,
    result: PDFProcessingResult,
    reason: str,
    post_commit: tuple[JobPostCommitAction, ...],
) -> JobHandlerResult:
    """Fail only the repair job while keeping the readable canonical document."""

    contract_issue = unicode_repair_contract_issue(
        durable_job=durable_job,
        result=result,
    )
    if contract_issue is not None:
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome=contract_issue,
            error_code=UNICODE_REPAIR_CONTRACT_ERROR,
            post_commit=post_commit,
        )
    job_id = durable_job.id
    if not isinstance(job_id, uuid.UUID):
        raise RuntimeError(UNICODE_REPAIR_CONTRACT_ERROR)
    error_code = _safe_pdf_failure_code(
        reason=reason,
        progress_code=durable_job.progress_code,
    )
    _job, changed = job_repository.fail(
        db,
        job_id=job_id,
        error_code=error_code,
        result=_repair_terminal_result(outcome="worker_failed"),
    )
    _restore_failed_unicode_repair(db=db, durable_job=durable_job)
    _schedule_repair_artifact_deletion(
        db=db,
        durable_job=durable_job,
        suffix="failed",
    )
    _record_unicode_repair_outcome(outcome="worker_failed")
    logger.warning(
        "document.pdf_unicode_repair.failed",
        extra={
            "job_id": str(job_id),
            "document_id": str(durable_job.document_id),
            "error_code": error_code,
            "job_changed": changed,
        },
    )
    return JobHandlerResult(
        value={"status": "webhook processed - unicode repair failed"},
        post_commit=post_commit,
    )


def _planned_parsed_text_reanchors(
    *,
    db: Session,
    document_id: uuid.UUID,
    raw_content: str,
    page_offset_map: dict[int, list[int]] | None,
) -> list[tuple[AnnotationThread, int, int, int | None]] | None:
    # Lock and measure scalar facts before hydrating user-controlled Text and
    # JSONB values. Historical rows predate today's field validation, so the
    # ORM query must not be the operation that discovers an oversized quote or
    # position object.
    preflight = db.execute(
        select(
            AnnotationThread.research_item_id.label("thread_id"),
            func.coalesce(func.octet_length(AnnotationThread.quote_text), 0).label(
                "quote_bytes"
            ),
            func.coalesce(
                func.octet_length(cast(AnnotationThread.position, Text)),
                0,
            ).label("position_bytes"),
        )
        .join(ResearchItem, ResearchItem.id == AnnotationThread.research_item_id)
        .where(
            ResearchItem.target_document_id == document_id,
            AnnotationThread.position.isnot(None),
            AnnotationThread.position["kind"].astext == "parsed_text",
        )
        .order_by(AnnotationThread.research_item_id)
        .with_for_update(of=AnnotationThread)
        .limit(UNICODE_REPAIR_MAX_REANCHOR_THREADS + 1)
    ).all()
    if len(preflight) > UNICODE_REPAIR_MAX_REANCHOR_THREADS:
        return None
    quote_bytes = sum(int(row.quote_bytes or 0) for row in preflight)
    position_bytes = sum(int(row.position_bytes or 0) for row in preflight)
    estimated_scan_characters = len(raw_content) * len(preflight) * 2
    if (
        quote_bytes > UNICODE_REPAIR_MAX_REANCHOR_QUOTE_UTF8_BYTES
        or position_bytes > UNICODE_REPAIR_MAX_REANCHOR_POSITION_UTF8_BYTES
        or estimated_scan_characters > UNICODE_REPAIR_MAX_REANCHOR_SCAN_CHARACTERS
    ):
        return None
    if not preflight:
        return []

    thread_ids = tuple(row.thread_id for row in preflight)
    threads = db.scalars(
        select(AnnotationThread)
        .where(AnnotationThread.research_item_id.in_(thread_ids))
        .options(
            load_only(
                AnnotationThread.research_item_id,
                AnnotationThread.quote_text,
                AnnotationThread.position,
            )
        )
        .order_by(AnnotationThread.research_item_id)
        .with_for_update(of=AnnotationThread)
    ).all()
    if len(threads) != len(thread_ids):
        return None
    page_ranges = tuple(
        (bounds[0], bounds[1], page)
        for page, bounds in sorted((page_offset_map or {}).items())
    )
    page_starts = tuple(start for start, _end, _page in page_ranges)
    planned: list[tuple[AnnotationThread, int, int, int | None]] = []
    for thread in threads:
        quote = thread.quote_text
        start = raw_content.find(quote)
        if start < 0:
            return None
        end = start + len(quote)
        if raw_content.find(quote, end) >= 0:
            return None
        page_index = bisect_right(page_starts, start) - 1
        page_number = (
            page_ranges[page_index][2]
            if page_index >= 0 and start < page_ranges[page_index][1]
            else None
        )
        planned.append((thread, start, end, page_number))
    return planned


def invalidate_document_reflow(
    *,
    db: Session,
    document_id: uuid.UUID,
) -> bool:
    """Hide derived reflow output and terminate work based on old canonical text."""

    artifact = db.get(DocumentReflow, document_id)
    if artifact is None or artifact.status == "failed":
        return False
    job_repository.fail(
        db,
        job_id=artifact.job_id,
        error_code=REFLOW_CANONICAL_REVISION_CHANGED,
        result={"outcome": "canonical_source_revision_changed"},
    )
    invalidated_at = datetime.now(timezone.utc)
    artifact.status = "failed"
    artifact.error_code = REFLOW_CANONICAL_REVISION_CHANGED
    artifact.completed_at = invalidated_at
    artifact.updated_at = invalidated_at
    logger.info(
        "document.reflow.invalidated",
        extra={
            "document_id": str(document_id),
            "reason": REFLOW_CANONICAL_REVISION_CHANGED,
        },
    )
    return True


def _validated_repair_context(
    *,
    db: Session,
    durable_job: DurableJob,
    result: PDFProcessingResult,
    post_commit: tuple[JobPostCommitAction, ...],
) -> _RepairContext | JobHandlerResult:
    contract_issue = unicode_repair_contract_issue(
        durable_job=durable_job,
        result=result,
    )
    if contract_issue is not None:
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome=contract_issue,
            error_code=UNICODE_REPAIR_CONTRACT_ERROR,
            post_commit=post_commit,
        )

    source_job_id = _unicode_repair_source_job_id(durable_job)
    document_id = durable_job.document_id
    current_job_id = durable_job.id
    if (
        source_job_id is None
        or not isinstance(document_id, uuid.UUID)
        or not isinstance(current_job_id, uuid.UUID)
    ):
        raise RuntimeError(UNICODE_REPAIR_CONTRACT_ERROR)

    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome="document_missing",
            post_commit=post_commit,
        )
    if (
        document.processing_job_id not in {source_job_id, current_job_id}
        or document.processing_status != DocumentProcessingStatus.COMPLETED.value
    ):
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome="document_generation_changed",
            error_code=UNICODE_REPAIR_OBSOLETE_ERROR,
            post_commit=post_commit,
        )

    payload = durable_job.payload
    current_content = document.raw_content or ""
    current_digest = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
    if payload.get("repair_source_content_digest") != current_digest:
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome="source_content_changed",
            error_code=UNICODE_REPAIR_OBSOLETE_ERROR,
            post_commit=post_commit,
        )

    candidate_content = result.raw_content
    if (
        payload.get("content_sha256") != document.sha256
        or result.s3_object_key != document.s3_object_key
        or not candidate_content
    ):
        return _terminate_rejected_unicode_repair(
            db=db,
            durable_job=durable_job,
            outcome="source_document_changed",
            error_code=UNICODE_REPAIR_OBSOLETE_ERROR,
            post_commit=post_commit,
        )
    return _RepairContext(
        source_job_id=source_job_id,
        current_job_id=current_job_id,
        document_id=document_id,
        document=document,
        current_content=current_content,
        candidate_content=candidate_content,
    )


def _plan_repair(
    *,
    db: Session,
    context: _RepairContext,
    page_offset_map: dict[int, list[int]] | None,
) -> _RepairPlan:
    assessment = assess_canonical_text_repair(
        current=context.current_content,
        candidate=context.candidate_content,
    )
    applied = assessment.safe_to_replace
    reason = (
        "improved"
        if applied
        else (
            "content_diverged"
            if assessment.reduces_unicode_corruption
            else "not_improved"
        )
    )
    reanchors: tuple[_ParsedTextReanchor, ...] = ()
    if applied:
        planned = _planned_parsed_text_reanchors(
            db=db,
            document_id=context.document_id,
            raw_content=context.candidate_content,
            page_offset_map=page_offset_map,
        )
        if planned is None:
            applied = False
            reason = "annotation_reanchor_unsafe"
        else:
            reanchors = tuple(planned)
    return _RepairPlan(
        applied=applied,
        reason=reason,
        current_replacement_count=assessment.current_replacement_count,
        candidate_replacement_count=assessment.candidate_replacement_count,
        reanchors=reanchors,
    )


def _apply_repair_plan(
    *,
    db: Session,
    context: _RepairContext,
    result: PDFProcessingResult,
    plan: _RepairPlan,
) -> None:
    for thread, start, end, page_number in plan.reanchors:
        position = dict(thread.position or {})
        position["start_offset"] = start
        position["end_offset"] = end
        position["page_number"] = page_number
        thread.start_offset = start
        thread.end_offset = end
        thread.page_number = page_number
        thread.position = position
    document_repository.update_canonical(
        db,
        document=context.document,
        update=DocumentUpdate(
            raw_content=context.candidate_content,
            parser_markdown_s3_key=result.parser_markdown_s3_key,
            parser_archive_s3_key=result.parser_archive_s3_key,
            parser_backend=result.parser_backend,
            parser_quality=result.parser_quality,
            parser_version=result.parser_version,
            parser_warning_code=result.parser_warning_code,
            page_offset_map=result.page_offset_map,
            processing_status=DocumentProcessingStatus.COMPLETED.value,
            processing_job_id=context.current_job_id,
        ),
        # The admin-scheduled repair is a system-owned canonical write. The
        # original requester may have removed their own library reference
        # after ingestion; durable job/document guards above are the authority.
        user=None,
        refresh_result=False,
    )
    document_search_repository.replace_passage_index(
        db,
        document_id=context.document.id,
        raw_content=context.candidate_content,
    )
    invalidate_document_reflow(db=db, document_id=context.document.id)


def _restore_unapplied_repair(*, context: _RepairContext) -> None:
    context.document.processing_job_id = context.source_job_id
    context.document.parser_quality = "text_only"
    context.document.parser_warning_code = UNICODE_REPLACEMENT_WARNING_CODE


def complete_unicode_repair(
    *,
    db: Session,
    durable_job: DurableJob,
    result: PDFProcessingResult,
    post_commit: tuple[JobPostCommitAction, ...],
) -> JobHandlerResult:
    """Atomically apply or reject one validated Unicode text repair result."""

    context = _validated_repair_context(
        db=db,
        durable_job=durable_job,
        result=result,
        post_commit=post_commit,
    )
    if isinstance(context, JobHandlerResult):
        return context
    plan = _plan_repair(
        db=db,
        context=context,
        page_offset_map=result.page_offset_map,
    )
    bounded_result = _bounded_repair_result(result=result, plan=plan)

    # The callback transaction already holds the durable-job row lock before
    # acquiring the Document lock. Complete first so a terminal race can never
    # leave canonical text pointing at a cancelled or failed repair job. Any
    # later exception rolls both transitions back with the surrounding savepoint.
    completed = _complete_pdf_job(
        db,
        job_id=context.current_job_id,
        result=result,
        persisted_result=bounded_result,
    )
    if not completed:
        return JobHandlerResult(
            value={"status": "webhook ignored - unicode repair job is terminal"},
            post_commit=post_commit,
        )
    if plan.applied:
        replaced_artifact_keys = {
            context.document.parser_markdown_s3_key,
            context.document.parser_archive_s3_key,
        } - {
            None,
            context.document.s3_object_key,
            result.parser_markdown_s3_key,
            result.parser_archive_s3_key,
        }
        _apply_repair_plan(db=db, context=context, result=result, plan=plan)
        schedule_storage_deletion(
            db,
            object_keys=sorted(
                key for key in replaced_artifact_keys if key is not None
            ),
            idempotency_key=f"unicode-repair:{context.current_job_id}:replaced",
            origin_operation_id=durable_job.origin_operation_id,
            correlation_id=durable_job.correlation_id,
        )
    else:
        _restore_unapplied_repair(context=context)
        _schedule_repair_artifact_deletion(
            db=db,
            durable_job=durable_job,
            suffix="not-applied",
        )

    logger.info(
        "document.pdf_unicode_repair.completed",
        extra={
            "job_id": str(context.current_job_id),
            "document_id": str(context.document.id),
            "repair_applied": plan.applied,
            "repair_reason": plan.reason,
            "previous_replacement_count": plan.current_replacement_count,
            "replacement_count": plan.candidate_replacement_count,
        },
    )
    _record_unicode_repair_outcome(outcome="applied" if plan.applied else plan.reason)
    changes = (
        (
            _document_change(
                action=DOCUMENT_PROCESSING_COMPLETED,
                document_id=context.document.id,
            ),
        )
        if plan.applied
        else ()
    )
    return JobHandlerResult(
        value={
            "status": "webhook processed - unicode repair",
            "document_id": str(context.document.id),
            "repair_applied": plan.applied,
            "repair_reason": plan.reason,
        },
        changes=changes,
        post_commit=post_commit,
    )
