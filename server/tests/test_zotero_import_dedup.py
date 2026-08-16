"""Focused Zotero import planning and short-transaction workflow tests."""

from __future__ import annotations

import gc
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters import zotero_gateway as gateway_module
from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.bootstrap.workflows.zotero import (
    _StagedZoteroImport,
    _execute_import_plan,
    _execute_planned_import,
)
from app.database.models import ZoteroImportSource
from app.modules.papers.domain import normalize_doi
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportItemResult,
)
from app.modules.integrations.zotero.application.zotero import (
    ZoteroAttachmentSnapshot,
    ZoteroImportPlan,
    ZoteroImportPlanItem,
    ZoteroItemSnapshot,
)
from app.modules.papers.application.ingestion import (
    AcceptedIngestion,
)
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
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
        id=42,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _item(key: str, *, doi: str | None = None) -> ZoteroItemSnapshot:
    return ZoteroItemSnapshot(
        item_key=key,
        title=f"Paper {key}",
        authors=("Researcher",),
        abstract=None,
        publish_date="2026-01-01",
        doi=doi,
        tags=(),
        date_added="2026-01-02T00:00:00Z",
        item_type="journalArticle",
        venue=None,
        collection_keys=(),
        has_pdf_attachment=True,
        has_metadata=True,
    )


def _operation():
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1234/abc", "10.1234/abc"),
        ("https://doi.org/10.1234/abc", "10.1234/abc"),
        ("doi:10.1234/abc", "10.1234/abc"),
        (None, None),
        ("  ", None),
    ],
)
def test_normalize_doi(value: str | None, expected: str | None) -> None:
    assert normalize_doi(value) == expected


def test_plan_import_links_existing_and_duplicate_doi_without_title_dedup() -> None:
    existing_document = SimpleNamespace(
        id=uuid4(),
        s3_object_key="documents/existing.pdf",
    )
    gateway = DefaultZoteroGateway(MagicMock(), connections=MagicMock())
    items = (
        _item("EXISTING", doi="10.1000/existing"),
        _item("FIRST001", doi="10.1000/new"),
        _item("SECOND01", doi="https://doi.org/10.1000/new"),
        _item("NODOI001"),
        _item("NODOI002"),
    )

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=None,
        ),
        patch.object(
            gateway_module.document_repository,
            "find_library_document_by_doi",
            side_effect=lambda _db, *, doi, **_kwargs: (
                existing_document if doi == "10.1000/existing" else None
            ),
        ),
        patch.object(
            gateway_module, "can_user_upload_paper", return_value=(True, None)
        ),
        patch.object(
            gateway_module,
            "get_remaining_paper_upload_slots",
            return_value=10,
        ),
    ):
        plan = gateway.plan_import(
            actor=_actor(),
            items=items,
            credential_revision=uuid4(),
        )

    assert [planned.disposition for planned in plan.items] == [
        "link_existing",
        "import",
        "link_batch",
        "import",
        "import",
    ]
    assert plan.items[0].document_id == existing_document.id
    assert plan.items[2].source_item_key == "FIRST001"
    assert plan.skipped_already_imported == 2
    assert plan.errors == ()


def test_plan_import_applies_remaining_capacity_only_to_new_documents() -> None:
    gateway = DefaultZoteroGateway(MagicMock(), connections=MagicMock())
    items = (_item("ITEM0001"), _item("ITEM0002"))

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=None,
        ),
        patch.object(
            gateway_module.document_repository,
            "find_library_document_by_doi",
            return_value=None,
        ),
        patch.object(
            gateway_module, "can_user_upload_paper", return_value=(True, None)
        ),
        patch.object(
            gateway_module,
            "get_remaining_paper_upload_slots",
            return_value=1,
        ),
    ):
        plan = gateway.plan_import(
            actor=_actor(),
            items=items,
            credential_revision=uuid4(),
        )

    assert [planned.item.item_key for planned in plan.items] == ["ITEM0001"]
    assert [error.zotero_item_key for error in plan.errors] == ["ITEM0002"]


class _StageExecutor:
    def __init__(self, capabilities: object, events: list[str]) -> None:
        self.capabilities = capabilities
        self.events = events
        self.inside_transaction = False

    def query(self, operation):  # type: ignore[no-untyped-def]
        assert not self.inside_transaction
        self.events.append("query")
        return operation(self.capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        assert not self.inside_transaction
        self.events.append("command:start")
        self.inside_transaction = True
        try:
            return operation(self.capabilities)
        finally:
            self.inside_transaction = False
            self.events.append("command:end")


@pytest.mark.asyncio
async def test_import_plan_keeps_remote_io_outside_commands() -> None:
    events: list[str] = []
    actor = _actor()
    item = _item("ITEM0001")
    attachment = ZoteroAttachmentSnapshot(
        item_key=item.item_key,
        import_source=ZoteroImportSource.PDF_ATTACHMENT,
        attachment_key="ATTACH01",
        source_url=None,
        annotations_json="[]",
    )
    content = _StagedZoteroImport(
        item=item,
        attachment=attachment,
        object_key="zotero-imports/job/ITEM0001.pdf",
        page_dimensions=((0, 612.0, 792.0),),
    )
    job_id = uuid4()
    document_id = uuid4()
    paper_ingestion = MagicMock()
    paper_ingestion.acquire = AsyncMock(
        side_effect=lambda **_kwargs: events.append("acquire")
    )
    paper_ingestion.accept.side_effect = lambda **kwargs: (
        events.append("accept_paper")
        or AcceptedIngestion(
            ingestion=LibraryPaperIngestionResponse.model_validate(
                {
                    "id": kwargs["job_id"],
                    "display_name": item.title,
                    "source_kind": "upload",
                    "state": "queued",
                    "stage": "queued",
                    "project_id": None,
                    "document_id": document_id,
                    "error_code": None,
                    "created_at": "2026-08-12T00:00:00Z",
                }
            ),
            replayed=False,
            processing_required=True,
        )
    )
    zotero = MagicMock()
    zotero.reserve_import_item.side_effect = lambda **_kwargs: events.append(
        "reserve_zotero"
    )
    zotero.complete_import_item.side_effect = lambda **_kwargs: (
        events.append("complete_zotero")
        or ZoteroImportItemResult(
            zotero_item_key=item.item_key,
            document_id=str(document_id),
            upload_job_id=str(job_id),
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            title=item.title,
        )
    )
    capabilities = SimpleNamespace(
        paper_ingestion=paper_ingestion,
        zotero=zotero,
    )
    executor = _StageExecutor(capabilities, events)
    operations = MagicMock()

    async def upload_pdf(**_kwargs):  # type: ignore[no-untyped-def]
        assert not executor.inside_transaction
        events.append("upload_external")

    operations.upload_pdf = AsyncMock(side_effect=upload_pdf)
    operations.download_job_pdf = AsyncMock(
        side_effect=lambda **_kwargs: events.append("download_external") or b"%PDF-1.4"
    )
    result = await _execute_import_plan(
        executor=executor,  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
        actor=actor,
        operation=_operation(),
        plan=ZoteroImportPlan(
            items=(ZoteroImportPlanItem(item=item, disposition="import"),),
            skipped_already_imported=0,
            errors=(),
        ),
        staged_by_item_key={item.item_key: content},
        credential_revision=uuid4(),
        maintain_claim=lambda: events.append("heartbeat"),
    )

    assert result.imported_count == 1
    assert events == [
        "heartbeat",
        "download_external",
        "heartbeat",
        "query",
        "acquire",
        "heartbeat",
        "upload_external",
        "heartbeat",
        "command:start",
        "accept_paper",
        "reserve_zotero",
        "complete_zotero",
        "command:end",
    ]


@pytest.mark.asyncio
async def test_fifty_item_import_holds_only_one_pdf_payload_at_a_time() -> None:
    class TrackedPdf(bytes):
        active = 0
        peak = 0

        def __new__(cls) -> "TrackedPdf":
            value = super().__new__(cls, b"%PDF" + b"x" * (2 * 1024 * 1024))
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
            return value

        def __del__(self) -> None:
            type(self).active -= 1

    class Operations:
        downloads = 0
        uploads = 0

        async def download_job_pdf(self, *, object_key: str) -> bytes:
            assert object_key.startswith("zotero-imports/job/")
            self.downloads += 1
            return TrackedPdf()

        async def upload_pdf(self, *, content: bytes) -> None:
            assert isinstance(content, TrackedPdf)
            self.uploads += 1

    class PaperIngestion:
        async def acquire(self, **_kwargs: object) -> None:
            return None

        async def release(self, **_kwargs: object) -> None:
            return None

        def accept(self, **kwargs: object) -> AcceptedIngestion:
            job_id = kwargs["job_id"]
            assert isinstance(job_id, type(uuid4()))
            return AcceptedIngestion(
                ingestion=LibraryPaperIngestionResponse.model_validate(
                    {
                        "id": job_id,
                        "display_name": "Zotero paper",
                        "source_kind": "upload",
                        "state": "queued",
                        "stage": "queued",
                        "project_id": None,
                        "document_id": uuid4(),
                        "error_code": None,
                        "created_at": "2026-08-12T00:00:00Z",
                    }
                ),
                replayed=False,
                processing_required=True,
            )

    class ZoteroMutations:
        def reserve_import_item(self, **_kwargs: object) -> None:
            return None

        def complete_import_item(self, **kwargs: object) -> ZoteroImportItemResult:
            item = kwargs["item"]
            accepted_document_id = kwargs["document_id"]
            upload_job_id = kwargs["upload_job_id"]
            assert isinstance(item, ZoteroItemSnapshot)
            return ZoteroImportItemResult(
                zotero_item_key=item.item_key,
                document_id=str(accepted_document_id),
                upload_job_id=str(upload_job_id),
                import_source=ZoteroImportSource.PDF_ATTACHMENT,
                title=item.title,
            )

    items = tuple(_item(f"ITEM{index:04}") for index in range(50))
    staged = {
        item.item_key: _StagedZoteroImport(
            item=item,
            attachment=ZoteroAttachmentSnapshot(
                item_key=item.item_key,
                import_source=ZoteroImportSource.PDF_ATTACHMENT,
                attachment_key="ATTACH01",
                source_url=None,
                annotations_json="[]",
            ),
            object_key=f"zotero-imports/job/{item.item_key}.pdf",
            page_dimensions=(),
        )
        for item in items
    }
    operations = Operations()
    executor = _StageExecutor(
        SimpleNamespace(
            paper_ingestion=PaperIngestion(),
            zotero=ZoteroMutations(),
        ),
        [],
    )

    result = await _execute_import_plan(
        executor=executor,  # type: ignore[arg-type]
        operations=operations,  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
        actor=_actor(),
        operation=_operation(),
        plan=ZoteroImportPlan(
            items=tuple(
                ZoteroImportPlanItem(item=item, disposition="import") for item in items
            ),
            skipped_already_imported=0,
            errors=(),
        ),
        staged_by_item_key=staged,
        credential_revision=uuid4(),
        maintain_claim=lambda: None,
    )
    gc.collect()

    assert result.imported_count == 50
    assert operations.downloads == operations.uploads == 50
    assert TrackedPdf.peak == 1
    assert TrackedPdf.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lose_on_heartbeat", "expected_acquires", "expected_releases"),
    [(2, 0, 0), (3, 1, 1)],
)
async def test_claim_loss_around_acquire_never_uploads_or_accepts(
    lose_on_heartbeat: int,
    expected_acquires: int,
    expected_releases: int,
) -> None:
    item = _item("ITEM0001")
    staged = _StagedZoteroImport(
        item=item,
        attachment=ZoteroAttachmentSnapshot(
            item_key=item.item_key,
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            attachment_key="ATTACH01",
            source_url=None,
            annotations_json="[]",
        ),
        object_key="zotero-imports/job/ITEM0001.pdf",
        page_dimensions=(),
    )
    paper_ingestion = MagicMock()
    paper_ingestion.acquire = AsyncMock(return_value=None)
    paper_ingestion.release = AsyncMock(return_value=None)
    operations = MagicMock()
    operations.download_job_pdf = AsyncMock(return_value=b"%PDF-staged")
    operations.upload_pdf = AsyncMock(return_value=None)
    heartbeat_count = 0

    def maintain_claim() -> None:
        nonlocal heartbeat_count
        heartbeat_count += 1
        if heartbeat_count == lose_on_heartbeat:
            raise AppError(
                code="zotero_callback_lease_lost",
                message="callback claim lost",
                kind=FailureKind.CONFLICT,
            )

    with pytest.raises(AppError, match="zotero_callback_lease_lost"):
        await _execute_planned_import(
            executor=_StageExecutor(  # type: ignore[arg-type]
                SimpleNamespace(
                    paper_ingestion=paper_ingestion,
                    zotero=MagicMock(),
                ),
                [],
            ),
            operations=operations,
            operation_factory=OperationContextFactory(),
            actor=_actor(),
            operation=_operation(),
            planned=ZoteroImportPlanItem(item=item, disposition="import"),
            staged=staged,
            credential_revision=uuid4(),
            maintain_claim=maintain_claim,
        )

    assert paper_ingestion.acquire.await_count == expected_acquires
    assert paper_ingestion.release.await_count == expected_releases
    operations.upload_pdf.assert_not_awaited()
    paper_ingestion.accept.assert_not_called()
