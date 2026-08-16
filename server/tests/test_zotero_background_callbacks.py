from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.workflows.zotero import ZoteroBackgroundWorkflow
from app.modules.integrations.zotero.application.zotero import ZoteroImportPlan
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)


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
                    "item_key": "ITEM1",
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
