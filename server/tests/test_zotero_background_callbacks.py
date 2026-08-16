from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.bootstrap.workflows.zotero import (
    ZoteroBackgroundWorkflow,
    _recoverable_auto_import_cursor,
)
from app.modules.integrations.zotero.application.zotero import ZoteroImportPlan
from app.modules.integrations.zotero.application.contracts import ZoteroImportRequest
from app.modules.jobs.application.contracts import (
    MAX_ZOTERO_ANNOTATIONS_BYTES,
    ZoteroImportWebhookData,
    ZoteroSyncWebhookData,
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
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation():
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


@pytest.mark.parametrize(
    "item_key",
    ["../ITEM1", "item0001", "ITEM001", "ITEM00001", "ITEM/001"],
)
def test_public_import_rejects_path_shaped_or_non_zotero_keys(
    item_key: str,
) -> None:
    with pytest.raises(ValidationError):
        ZoteroImportRequest(item_keys=[item_key])


def test_internal_callback_binds_keys_and_staging_path_to_task() -> None:
    task_id = uuid4()
    payload = {
        "task_id": str(task_id),
        "operation": "import",
        "credential_revision": str(uuid4()),
        "credential_outcome": "verified",
        "items": [
            {
                "item_key": "ITEM0001",
                "status": "ready",
                "s3_object_key": f"zotero-imports/{task_id}/../ITEM0001.pdf",
                "metadata": {
                    "item_key": "ITEM0001",
                    "title": "Paper",
                    "item_type": "journalArticle",
                },
                "attachment": {
                    "item_key": "ITEM0001",
                    "attachment_key": "ATTACH01",
                    "import_source": "pdf_attachment",
                    "annotations_json": "[]",
                },
            }
        ],
    }

    with pytest.raises(ValidationError):
        ZoteroImportWebhookData.model_validate(payload)


def test_internal_callback_caps_annotation_content() -> None:
    payload = {
        "task_id": str(uuid4()),
        "operation": "sync",
        "credential_revision": str(uuid4()),
        "credential_outcome": "verified",
        "updates": [
            {
                "item_key": "ITEM0001",
                "attachment_key": "ATTACH01",
                "annotations_json": "x" * (MAX_ZOTERO_ANNOTATIONS_BYTES + 1),
            }
        ],
    }

    with pytest.raises(ValidationError):
        ZoteroSyncWebhookData.model_validate(payload)


def test_auto_import_cursor_stops_before_transient_middle_failure() -> None:
    callback = ZoteroSyncWebhookData.model_validate(
        {
            "task_id": str(uuid4()),
            "operation": "sync",
            "credential_revision": str(uuid4()),
            "credential_outcome": "verified",
            "auto_imports": [
                {
                    "item_key": "ITEM0001",
                    "version": 50,
                    "status": "failed",
                    "error_code": "zotero_item_not_found",
                },
                {
                    "item_key": "ITEM0002",
                    "version": 50,
                    "status": "failed",
                    "error_code": "zotero_rate_limited",
                },
                {
                    "item_key": "ITEM0003",
                    "version": 50,
                    "status": "failed",
                    "error_code": "zotero_item_not_found",
                },
            ],
            "library_version": 80,
            "auto_import_base_version": 50,
            "auto_import_base_start": 100,
            "auto_import_caught_up_version": 80,
        }
    )

    cursor = _recoverable_auto_import_cursor(
        callback=callback,
        import_result={
            "items": [
                {
                    "zotero_item_key": "ITEM0001",
                    "status": "failed",
                    "error_code": "zotero_item_not_found",
                },
                {
                    "zotero_item_key": "ITEM0002",
                    "status": "failed",
                    "error_code": "zotero_rate_limited",
                },
                {
                    "zotero_item_key": "ITEM0003",
                    "status": "failed",
                    "error_code": "zotero_item_not_found",
                },
            ]
        },
    )

    assert cursor is not None
    assert cursor.library_version == 50
    assert cursor.start == 101


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self.capabilities = capabilities

    def query(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)


@pytest.mark.asyncio
async def test_invalid_credential_callback_is_revision_scoped_and_fails_job() -> None:
    job_id = uuid4()
    revision = uuid4()
    integrations = MagicMock()
    zotero = MagicMock()
    zotero.claim_background_operation.return_value = SimpleNamespace(
        acquired=True,
        claim_id=uuid4(),
    )
    zotero.credential_revision_is_current.return_value = True
    workflow = ZoteroBackgroundWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(integrations=integrations, zotero=zotero)
        ),
        operations=MagicMock(),
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=_operation(),
        job_id=job_id,
        payload={
            "task_id": str(job_id),
            "operation": "import",
            "credential_revision": str(revision),
            "credential_outcome": "invalid",
            "error_code": "zotero_credentials_invalid",
            "items": [],
        },
    )

    assert result == {"accepted": True, "status": "failed"}
    assert (
        integrations.record_outcome.call_args.kwargs["credential_revision"] == revision
    )
    failure = zotero.fail_background_operation.call_args.kwargs
    assert failure["actor"].id == 7
    assert failure["operation_id"] == job_id
    assert failure["error_code"] == "zotero_credentials_invalid"
    zotero.complete_background_operation.assert_not_called()


@pytest.mark.asyncio
async def test_failed_items_complete_as_partial_result_without_provider_errors() -> (
    None
):
    job_id = uuid4()
    revision = uuid4()
    integrations = MagicMock()
    zotero = MagicMock()
    zotero.claim_background_operation.return_value = SimpleNamespace(
        acquired=True,
        claim_id=uuid4(),
    )
    zotero.credential_revision_is_current.return_value = True
    zotero.plan_import.return_value = ZoteroImportPlan(
        items=(),
        skipped_already_imported=0,
        errors=(),
    )
    zotero.complete_background_operation.return_value = True
    workflow = ZoteroBackgroundWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(integrations=integrations, zotero=zotero)
        ),
        operations=MagicMock(),
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=_operation(),
        job_id=job_id,
        payload={
            "task_id": str(job_id),
            "operation": "import",
            "credential_revision": str(revision),
            "credential_outcome": "verified",
            "error_code": None,
            "items": [
                {
                    "item_key": "ITEM0001",
                    "status": "failed",
                    "error_code": "zotero_pdf_unavailable",
                }
            ],
        },
    )

    assert result == {"accepted": True}
    applied = zotero.complete_background_operation.call_args.kwargs["result"]
    assert applied["counts"] == {
        "total": 1,
        "succeeded": 0,
        "failed": 1,
        "skipped": 0,
    }
    assert applied["items"][0]["error_code"] == "zotero_pdf_unavailable"


@pytest.mark.asyncio
async def test_rotated_credential_rejects_late_worker_results() -> None:
    job_id = uuid4()
    old_revision = uuid4()
    integrations = MagicMock()
    zotero = MagicMock()
    zotero.claim_background_operation.return_value = SimpleNamespace(
        acquired=True,
        claim_id=uuid4(),
    )
    zotero.credential_revision_is_current.return_value = False
    workflow = ZoteroBackgroundWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(integrations=integrations, zotero=zotero)
        ),
        operations=MagicMock(),
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=_operation(),
        job_id=job_id,
        payload={
            "task_id": str(job_id),
            "operation": "import",
            "credential_revision": str(old_revision),
            "credential_outcome": "verified",
            "error_code": None,
            "items": [],
        },
    )

    assert result == {"accepted": True, "status": "failed"}
    failure = zotero.fail_background_operation.call_args.kwargs
    assert failure["error_code"] == "zotero_credentials_rotated"
    integrations.record_outcome.assert_not_called()
    zotero.plan_import.assert_not_called()
    zotero.complete_background_operation.assert_not_called()


@pytest.mark.asyncio
async def test_rotation_after_initial_check_blocks_mutation_and_cleans_staging() -> (
    None
):
    job_id = uuid4()
    revision = uuid4()
    integrations = MagicMock()
    zotero = MagicMock()
    zotero.claim_background_operation.return_value = SimpleNamespace(
        acquired=True,
        claim_id=uuid4(),
    )
    zotero.credential_revision_is_current.return_value = True
    zotero.plan_import.side_effect = AppError(
        code="zotero_credentials_rotated",
        message="connection changed",
        kind=FailureKind.CONFLICT,
    )
    operations = MagicMock()
    operations.download_job_pdf = AsyncMock(return_value=b"%PDF-staged")
    operations.delete_job_pdf = AsyncMock(return_value=None)
    workflow = ZoteroBackgroundWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(integrations=integrations, zotero=zotero)
        ),
        operations=operations,
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=_operation(),
        job_id=job_id,
        payload={
            "task_id": str(job_id),
            "operation": "import",
            "credential_revision": str(revision),
            "credential_outcome": "verified",
            "error_code": None,
            "items": [
                {
                    "item_key": "ITEM0001",
                    "version": 11,
                    "status": "ready",
                    "s3_object_key": f"zotero-imports/{job_id}/ITEM0001.pdf",
                    "metadata": {
                        "item_key": "ITEM0001",
                        "title": "Paper",
                        "item_type": "journalArticle",
                        "version": 11,
                    },
                    "attachment": {
                        "item_key": "ITEM0001",
                        "import_source": "pdf_attachment",
                        "attachment_key": "ATTACH01",
                        "annotations_json": "[]",
                    },
                    "page_dimensions": [],
                }
            ],
        },
    )

    assert result == {"accepted": True, "status": "failed"}
    zotero.plan_import.assert_called_once()
    zotero.reserve_import_item.assert_not_called()
    zotero.complete_import_item.assert_not_called()
    operations.delete_job_pdf.assert_awaited_once_with(
        object_key=f"zotero-imports/{job_id}/ITEM0001.pdf"
    )
    assert (
        zotero.fail_background_operation.call_args.kwargs["error_code"]
        == "zotero_credentials_rotated"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["cancelled", "completed"])
async def test_terminal_callback_replay_has_no_side_effects(
    terminal_status: str,
) -> None:
    job_id = uuid4()
    integrations = MagicMock()
    zotero = MagicMock()
    zotero.claim_background_operation.return_value = SimpleNamespace(
        acquired=False,
        claim_id=None,
        job=SimpleNamespace(status=terminal_status),
    )
    operations = MagicMock()
    workflow = ZoteroBackgroundWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(integrations=integrations, zotero=zotero)
        ),
        operations=operations,
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=_operation(),
        job_id=job_id,
        payload={
            "task_id": str(job_id),
            "operation": "import",
            "credential_revision": str(uuid4()),
            "credential_outcome": "verified",
            "items": [],
        },
    )

    assert result == {"accepted": False}
    integrations.record_outcome.assert_not_called()
    zotero.credential_revision_is_current.assert_not_called()
    zotero.plan_import.assert_not_called()
    zotero.complete_background_operation.assert_not_called()
    zotero.fail_background_operation.assert_not_called()
    assert operations.mock_calls == []
