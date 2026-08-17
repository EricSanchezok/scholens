from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.paper_ingestion import (
    DefaultPaperIngestionLimits,
    DefaultPaperSourceResolver,
    SafePdfUrlSource,
)
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.helpers.ai_limits import AILimitExceeded
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.ingestion import AcceptedIngestion, IngestPaper
from app.modules.papers.application.upload_sessions import PaperUploadRecord
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation():
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _accepted(*, replayed: bool = False) -> AcceptedIngestion:
    job_id = uuid4()
    return AcceptedIngestion(
        ingestion=LibraryPaperIngestionResponse.model_validate(
            {
                "id": job_id,
                "display_name": "fixture.pdf",
                "source_kind": "upload",
                "state": "queued",
                "stage": "queued",
                "project_id": None,
                "document_id": uuid4(),
                "failure": None,
                "created_at": "2026-08-12T00:00:00Z",
            }
        ),
        replayed=replayed,
        processing_required=True,
    )


class FakeJournal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, **entry: object) -> object:
        self.entries.append(entry)
        return object()

    def append_many(
        self,
        *,
        actor: object,
        operation: object,
        changes: object,
    ) -> tuple[object, ...]:
        del actor, operation
        normalized = tuple(changes)  # type: ignore[arg-type]
        self.entries.extend({"change": change} for change in normalized)
        return tuple(object() for _ in normalized)


@pytest.mark.asyncio
async def test_ingestion_validates_then_accepts_one_atomic_snapshot() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    gateway = MagicMock()
    gateway.accept.return_value = _accepted()
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    operation = _operation()
    proposed_job_id = uuid4()
    accepted = ingestion.accept(
        actor=_actor(),
        operation=operation,
        prepared=prepared,
        project_id=None,
        idempotency_key=" request-1 ",
        job_id=proposed_job_id,
    )

    validator.validate.assert_called_once_with(
        content=b"%PDF fixture", source="fixture.pdf"
    )
    gateway.accept.assert_called_once()
    assert gateway.accept.call_args.kwargs["idempotency_key"] == "request-1"
    assert gateway.accept.call_args.kwargs["job_id"] == proposed_job_id
    assert accepted.ingestion.state == "queued"
    assert len(journal.entries) == 1


def test_idempotent_replay_does_not_journal_a_second_job() -> None:
    gateway = MagicMock()
    gateway.accept.return_value = _accepted(replayed=True)
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=MagicMock(),
        limits=MagicMock(),
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    accepted = ingestion.accept(
        actor=_actor(),
        operation=_operation(),
        prepared=MagicMock(
            content=b"%PDF",
            filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
        ),
        project_id=None,
        idempotency_key="request-1",
        job_id=uuid4(),
    )

    assert accepted.replayed
    assert journal.entries == []


def test_retry_revalidates_persisted_pdf_without_http_rate_charge() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=MagicMock(),
        journal=FakeJournal(),  # type: ignore[arg-type]
    )

    prepared = ingestion.prepare_persisted(
        content=b"%PDF persisted",
        filename="paper.pdf",
        display_name="Paper",
        source_kind="arxiv",
    )

    assert prepared.content == b"%PDF persisted"
    assert prepared.display_name == "Paper"
    assert prepared.source_kind == "arxiv"
    validator.validate.assert_called_once_with(
        content=b"%PDF persisted", source="paper.pdf"
    )
    limits.enforce_rate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expected_id"),
    [
        ("1706.03762", "1706.03762"),
        ("arXiv:1706.03762v5", "1706.03762v5"),
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762.pdf", "1706.03762"),
    ],
)
async def test_paper_source_resolver_normalizes_arxiv_sources(
    value: str, expected_id: str
) -> None:
    openalex = MagicMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    assert await resolver.resolve(
        actor=_actor(),
        operation=_operation(),
        kind="arxiv",
        value=value,
    ) == (f"https://arxiv.org/pdf/{expected_id}")
    openalex.find_by_doi.assert_not_called()


@pytest.mark.asyncio
async def test_paper_source_resolver_uses_openalex_pdf_for_doi() -> None:
    openalex = MagicMock()
    openalex.find_by_doi = AsyncMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)
    work = MagicMock()
    work.best_oa_location = None
    work.primary_location.pdf_url = "https://papers.example/paper.pdf"
    openalex.find_by_doi.return_value = work
    actor = _actor()
    operation = _operation()

    resolved = await resolver.resolve(
        actor=actor,
        operation=operation,
        kind="doi",
        value="https://doi.org/10.1000/example",
    )

    assert resolved == "https://papers.example/paper.pdf"
    openalex.find_by_doi.assert_awaited_once_with(
        actor=actor,
        operation=operation,
        doi="10.1000/example",
    )


@pytest.mark.asyncio
async def test_paper_source_resolver_prefers_best_openalex_oa_location() -> None:
    openalex = MagicMock()
    openalex.find_by_doi = AsyncMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)
    work = MagicMock()
    work.best_oa_location.pdf_url = "https://repository.example/paper.pdf"
    work.primary_location.pdf_url = "https://publisher.example/paper.pdf"
    openalex.find_by_doi.return_value = work

    resolved = await resolver.resolve(
        actor=_actor(),
        operation=_operation(),
        kind="doi",
        value="10.1000/example",
    )

    assert resolved == "https://repository.example/paper.pdf"


@pytest.mark.asyncio
async def test_invalid_doi_is_rejected_before_openalex_access() -> None:
    openalex = MagicMock()
    openalex.find_by_doi = AsyncMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    with pytest.raises(AppError) as raised:
        await resolver.resolve(
            actor=_actor(),
            operation=_operation(),
            kind="doi",
            value="not-a-doi",
        )

    assert raised.value.code == "paper_source_pdf_unavailable"
    openalex.find_by_doi.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_openalex_connection_is_preserved_for_doi_action() -> None:
    openalex = MagicMock()
    openalex.find_by_doi = AsyncMock(
        side_effect=AppError(
            code="openalex_credential_required",
            message="OpenAlex connection required",
            kind=FailureKind.CONFLICT,
            retryable=True,
            details={"required_integration": "openalex"},
        )
    )
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    with pytest.raises(AppError) as raised:
        await resolver.resolve(
            actor=_actor(),
            operation=_operation(),
            kind="doi",
            value="10.1000/example",
        )

    assert raised.value.code == "openalex_credential_required"
    assert raised.value.details == {"required_integration": "openalex"}


@pytest.mark.asyncio
async def test_openalex_work_without_open_pdf_is_unavailable() -> None:
    openalex = MagicMock()
    openalex.find_by_doi = AsyncMock(
        return_value=MagicMock(
            best_oa_location=None,
            primary_location=None,
            open_access=None,
        )
    )
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    with pytest.raises(AppError) as raised:
        await resolver.resolve(
            actor=_actor(),
            operation=_operation(),
            kind="doi",
            value="10.1000/example",
        )

    assert raised.value.code == "paper_source_pdf_unavailable"


@pytest.mark.asyncio
async def test_direct_pdf_url_bypasses_openalex() -> None:
    openalex = MagicMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    result = await resolver.resolve(
        actor=_actor(),
        operation=_operation(),
        kind="url",
        value="https://papers.example/paper.pdf",
    )

    assert result == "https://papers.example/paper.pdf"
    openalex.find_by_doi.assert_not_called()


@pytest.mark.asyncio
async def test_paper_source_resolver_rejects_non_arxiv_hosts() -> None:
    openalex = MagicMock()
    resolver = DefaultPaperSourceResolver(openalex=openalex)

    with pytest.raises(AppError) as raised:
        await resolver.resolve(
            actor=_actor(),
            operation=_operation(),
            kind="arxiv",
            value="https://example.com/abs/2401.01234",
        )

    assert raised.value.code == "paper_source_pdf_unavailable"
    openalex.find_by_doi.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("File too large (max 50MB)", "upload_too_large"),
        ("PDF is encrypted", "pdf_encrypted"),
        (
            "PDF URL must resolve only to public addresses",
            "paper_source_unsafe_address",
        ),
        ("File too small to be a valid PDF", "invalid_pdf"),
        ("Failed to download PDF from URL", "paper_source_pdf_unavailable"),
    ],
)
async def test_safe_pdf_source_preserves_actionable_error_codes(
    message: str, expected_code: str
) -> None:
    with patch(
        "app.bootstrap.adapters.paper_ingestion.validate_url_and_fetch_pdf",
        return_value=(False, b"", message),
    ):
        with pytest.raises(AppError) as raised:
            await SafePdfUrlSource().fetch(url="https://papers.example/paper.pdf")

    assert raised.value.code == expected_code


@pytest.mark.asyncio
async def test_upload_session_rejects_a_different_ingestion_project() -> None:
    executor = MagicMock()
    prepared_project_id = uuid4()
    executor.command.side_effect = [
        PaperUploadRecord(
            id=uuid4(),
            actor_id=_actor().id,
            project_id=prepared_project_id,
            filename="paper.pdf",
            size_bytes=12,
            sha256="01" * 32,
            object_key="uploads/7/session/source.pdf",
            status="claimed",
            expires_at=MagicMock(),
            lease_expires_at=MagicMock(),
            lease_token=uuid4(),
        ),
        None,
    ]
    workflow = PaperIngestionWorkflow(
        executor=executor,
        url_source=MagicMock(),
        source_resolver=MagicMock(),
        operation_factory=OperationContextFactory(),
        jobs=MagicMock(),
    )

    with pytest.raises(AppError) as raised:
        await workflow.from_upload_session(
            actor=_actor(),
            operation=_operation(),
            upload_id=uuid4(),
            project_id=uuid4(),
            idempotency_key=None,
            ip_address="127.0.0.1",
        )

    assert raised.value.code == "paper_upload_project_mismatch"
    assert executor.command.call_count == 2


@pytest.mark.asyncio
async def test_upload_rate_dependency_failure_is_retryable_unavailable() -> None:
    with patch(
        "app.bootstrap.adapters.paper_ingestion.enforce_rate_limit",
        AsyncMock(side_effect=AILimitExceeded("rate_limit_unavailable")),
    ):
        with pytest.raises(AppError) as raised:
            await DefaultPaperIngestionLimits().enforce_rate(
                actor=_actor(),
                ip_address="127.0.0.1",
            )

    assert raised.value.code == "rate_limit_unavailable"
    assert raised.value.kind is FailureKind.UNAVAILABLE


@pytest.mark.asyncio
async def test_upload_session_releases_lease_when_version_read_is_unavailable() -> None:
    executor = MagicMock()
    upload_id = uuid4()
    lease_token = uuid4()
    executor.command.side_effect = [
        PaperUploadRecord(
            id=upload_id,
            actor_id=_actor().id,
            project_id=None,
            filename="paper.pdf",
            size_bytes=12,
            sha256="01" * 32,
            object_key="uploads/7/session/source.pdf",
            status="claimed",
            expires_at=MagicMock(),
            lease_expires_at=MagicMock(),
            lease_token=lease_token,
        ),
        None,
    ]
    workflow = PaperIngestionWorkflow(
        executor=executor,
        url_source=MagicMock(),
        source_resolver=MagicMock(),
        operation_factory=OperationContextFactory(),
        jobs=MagicMock(),
    )

    with patch(
        "app.bootstrap.workflows.paper_ingestion.s3_service.staging_object_metadata",
        side_effect=RuntimeError("s3_head_failed"),
    ):
        with pytest.raises(AppError) as raised:
            await workflow.from_upload_session(
                actor=_actor(),
                operation=_operation(),
                upload_id=upload_id,
                project_id=None,
                idempotency_key=None,
                ip_address="127.0.0.1",
            )

    assert raised.value.code == "paper_upload_unavailable"
    assert raised.value.kind is FailureKind.UNAVAILABLE
    assert executor.command.call_count == 2
    release = executor.command.call_args_list[1].args[0]
    capabilities = MagicMock()
    release(capabilities)
    capabilities.paper_uploads.release.assert_called_once_with(
        actor=_actor(),
        upload_id=upload_id,
        lease_token=lease_token,
        failed=False,
    )


def test_cancel_journals_only_when_gateway_changes_state() -> None:
    gateway = MagicMock()
    gateway.cancel.return_value = True
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=MagicMock(),
        limits=MagicMock(),
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )
    job_id = uuid4()

    assert ingestion.cancel(actor=_actor(), operation=_operation(), job_id=job_id)
    assert len(journal.entries) == 1
    assert str(journal.entries[0]["action"]) == "job.failed"
