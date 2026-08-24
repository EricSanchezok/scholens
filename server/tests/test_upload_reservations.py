from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    Project,
    SubscriptionPlan,
    UploadReservation,
)
from app.shared.domain import AppError, FailureKind
from app.bootstrap.adapters.upload_reservations import (
    _active_account_reservations,
    reassign_project_quota_owner,
    reserve_upload,
)
from app.modules.jobs.infrastructure.repository import PersistedJob
from app.modules.billing.domain import entitlements_for


def _quota_patches(*, active_count: int = 0, active_size_kb: int = 0):
    return (
        patch("app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_entitlements",
            return_value=SimpleNamespace(
                limits=entitlements_for(SubscriptionPlan.BASIC)
            ),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._active_account_reservations",
            return_value=(active_count, active_size_kb),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_reference_count",
            return_value=0,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._has_active_duplicate_reservation",
            return_value=False,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_storage_kb",
            return_value=0,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._account_has_active_digest_reservation",
            return_value=False,
        ),
    )


def _durable_job(*, requester_id: int, project_id=None) -> DurableJob:
    job_id = uuid4()
    return DurableJob(
        id=job_id,
        operation=JobOperation.PDF_PROCESS.value,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=requester_id,
        project_id=project_id,
        idempotency_key=f"pdf-reservation:{job_id}",
        status=JobStatus.PENDING.value,
        payload={"input_size_bytes": 2_048},
    )


def _reservation(
    *,
    owner_id: int,
    digest: str,
    project_id=None,
    reference_count: int,
    size_kb: int,
    requester_id: int | None = None,
    add_to_library: bool | None = None,
) -> tuple[UploadReservation, DurableJob]:
    job = _durable_job(
        requester_id=requester_id if requester_id is not None else owner_id,
        project_id=project_id,
    )
    reservation = UploadReservation(
        id=job.id,
        quota_owner_id=owner_id,
        content_sha256=digest,
        display_name="pending.pdf",
        source_kind="upload",
        reserved_reference_count=reference_count,
        reserved_size_kb=size_kb,
        add_to_library=add_to_library,
    )
    reservation.job = job
    return reservation, job


def test_active_account_reservations_include_both_billing_roles() -> None:
    db = MagicMock()
    db.execute.return_value.one.return_value = (3, 7)

    assert _active_account_reservations(db, owner_id=17) == (3, 7)

    statement = db.execute.call_args.args[0]
    sql = str(statement)
    assert "upload_reservations.quota_owner_id" in sql
    assert "upload_reservations.library_quota_owner_id" in sql
    assert "upload_reservations.reserved_reference_count" in sql
    assert "upload_reservations.library_reserved_reference_count" in sql


def test_personal_upload_is_reserved_to_requester() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17)
    patches = _quota_patches()

    with (
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=PersistedJob(job=durable_job, created=True),
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_025,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="a" * 64,
        )

    job = result.reservation
    assert job.job.requested_by_id == 17
    assert job.quota_owner_id == 17
    assert job.job.project_id is None
    assert job.reserved_size_kb == 2
    assert job.job.status == JobStatus.PENDING.value
    quota_lock.assert_called_once_with(db, user_id=17)
    db.add.assert_called_once_with(job)
    db.flush.assert_called_once()
    db.commit.assert_not_called()


def test_project_upload_is_billed_to_owner_not_collaborator() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Shared corpus", owner_id=91)
    db = MagicMock()
    db.scalar.side_effect = [None, 0, 3]
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17, project_id=project_id)
    patches = _quota_patches()

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission_for_update",
            return_value=SimpleNamespace(project=project),
        ) as permission,
        patch(
            "app.bootstrap.adapters.upload_reservations._unattached_project_reservations",
            return_value=2,
        ),
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=PersistedJob(job=durable_job, created=True),
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=project_id,
            input_size_bytes=4_096,
            original_filename="shared.pdf",
            display_name="shared.pdf",
            source_kind="upload",
            content_sha256="b" * 64,
        )

    job = result.reservation
    permission.assert_called_once_with(
        db,
        project_id=project_id,
        user_id=17,
        permission="manage_papers",
    )
    assert quota_lock.call_count == 2
    quota_lock.assert_any_call(db, user_id=17)
    quota_lock.assert_any_call(db, user_id=91)
    assert job.job.requested_by_id == 17
    assert job.quota_owner_id == 91
    assert job.job.project_id == project_id
    assert job.add_to_library is True
    assert job.library_quota_owner_id == 17
    assert job.library_reserved_reference_count == 1
    assert job.library_reserved_size_kb == 4


def test_active_reservations_prevent_concurrent_paper_quota_bypass() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    requester = MagicMock(id=17)
    patches = _quota_patches(active_count=300)

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="c" * 64,
        )

    assert error.value.code == "paper_quota_exceeded"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_same_document_cannot_be_reserved_twice_for_one_library() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    requester = MagicMock(id=17)
    patches = _quota_patches()

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patch(
            "app.bootstrap.adapters.upload_reservations._has_active_duplicate_reservation",
            return_value=True,
        ),
        patches[6],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="c" * 64,
        )

    assert error.value.code == "document_upload_in_progress"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_existing_account_document_still_consumes_a_new_project_slot() -> None:
    project_id = uuid4()
    document_id = uuid4()
    project = Project(id=project_id, title="Full project", owner_id=91)
    db = MagicMock()
    db.scalar.side_effect = [document_id, 0, 0, 300]
    patches = _quota_patches()
    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission_for_update",
            return_value=SimpleNamespace(project=project),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._unattached_project_reservations",
            return_value=0,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.contains_document",
            return_value=True,
        ),
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=MagicMock(id=17),
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=project_id,
            input_size_bytes=1_024,
            original_filename="shared.pdf",
            display_name="shared.pdf",
            source_kind="upload",
            content_sha256="f" * 64,
        )

    assert error.value.code == "project_paper_quota_exceeded"


def test_empty_upload_is_rejected_before_any_reservation() -> None:
    db = MagicMock()

    with pytest.raises(AppError) as error:
        reserve_upload(
            db,
            requester=MagicMock(id=17),
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=0,
            original_filename="empty.pdf",
            display_name="empty.pdf",
            source_kind="upload",
            content_sha256="d" * 64,
        )

    assert error.value.code == "empty_upload"
    db.execute.assert_not_called()
    db.add.assert_not_called()


def test_idempotency_key_returns_the_original_reservation() -> None:
    requester = MagicMock(id=17)
    existing_job = _durable_job(requester_id=17)
    existing_job.idempotency_key = "pdf-ingestion:17:library:request-1"
    existing_job.payload = {"content_sha256": "e" * 64}
    reservation = UploadReservation(
        id=existing_job.id,
        quota_owner_id=17,
        content_sha256="e" * 64,
        display_name="paper.pdf",
        source_kind="upload",
    )
    reservation.job = existing_job
    db = MagicMock()
    db.get.return_value = reservation

    with (
        patch("app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.find_by_idempotency_key",
            return_value=existing_job,
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="e" * 64,
            idempotency_key="request-1",
        )

    assert result.reservation is reservation
    assert result.created is False
    db.add.assert_not_called()


def test_idempotency_key_does_not_resurrect_a_cancelled_ingestion() -> None:
    requester = MagicMock(id=17)
    existing_job = _durable_job(requester_id=17)
    existing_job.idempotency_key = "pdf-ingestion:17:library:request-1"
    existing_job.payload = {"content_sha256": "e" * 64}
    existing_job.status = JobStatus.CANCELLED.value
    reservation = UploadReservation(
        id=existing_job.id,
        quota_owner_id=17,
        content_sha256="e" * 64,
        display_name="paper.pdf",
        source_kind="upload",
    )
    reservation.job = existing_job
    db = MagicMock()
    db.get.return_value = reservation

    with (
        patch("app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.find_by_idempotency_key",
            return_value=existing_job,
        ),
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="e" * 64,
            idempotency_key="request-1",
        )

    assert error.value.code == "paper_ingestion_cancelled"
    db.add.assert_not_called()


def test_idempotency_key_rejects_changed_library_intent() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Shared corpus", owner_id=91)
    requester = MagicMock(id=17)
    existing_job = _durable_job(requester_id=17, project_id=project_id)
    existing_job.payload = {"content_sha256": "e" * 64}
    reservation = UploadReservation(
        id=existing_job.id,
        quota_owner_id=91,
        content_sha256="e" * 64,
        display_name="paper.pdf",
        source_kind="upload",
        add_to_library=False,
    )
    reservation.job = existing_job
    db = MagicMock()
    db.scalar.return_value = project
    db.get.return_value = reservation

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission_for_update",
            return_value=SimpleNamespace(project=project),
        ),
        patch("app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.find_by_idempotency_key",
            return_value=existing_job,
        ),
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=project_id,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="e" * 64,
            add_to_library=True,
            idempotency_key="request-1",
        )

    assert error.value.code == "idempotency_key_reused"


def _run_transfer(
    *,
    project: Project,
    active_rows: list[tuple[UploadReservation, DurableJob]],
    old_documents: list[Document] | None = None,
    new_documents: list[Document] | None = None,
) -> tuple[MagicMock, MagicMock]:
    db = MagicMock()
    db.scalar.side_effect = [1, 0]
    reservations_by_id = {
        reservation.id: reservation for reservation, _job in active_rows
    }
    db.get.side_effect = lambda model, item_id: (
        reservations_by_id.get(item_id) if model is UploadReservation else None
    )
    completed_documents = MagicMock(
        side_effect=[old_documents or [], new_documents or []]
    )
    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"
        ) as quota_lock,
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            side_effect=lambda _db, *, user_id: MagicMock(id=user_id),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_entitlements",
            return_value=SimpleNamespace(
                limits=entitlements_for(SubscriptionPlan.BASIC)
            ),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._locked_transfer_reservations",
            return_value=active_rows,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_documents",
            completed_documents,
        ),
    ):
        reassign_project_quota_owner(db, project=project, new_owner_id=20)
    return db, quota_lock


def test_project_transfer_reprices_old_owner_pending_duplicate_for_both_owners() -> (
    None
):
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, transferred_job = _reservation(
        owner_id=10,
        digest="e" * 64,
        project_id=project.id,
        reference_count=1,
        size_kb=2,
    )
    old_duplicate, old_duplicate_job = _reservation(
        owner_id=10,
        digest="e" * 64,
        reference_count=0,
        size_kb=0,
    )

    db, quota_lock = _run_transfer(
        project=project,
        active_rows=[
            (transferred, transferred_job),
            (old_duplicate, old_duplicate_job),
        ],
    )

    assert quota_lock.call_args_list == [
        ((db,), {"user_id": 10}),
        ((db,), {"user_id": 20}),
    ]
    assert transferred.quota_owner_id == 20
    assert transferred.reserved_reference_count == 1
    assert transferred.reserved_size_kb == 2
    assert old_duplicate.quota_owner_id == 10
    assert old_duplicate.reserved_reference_count == 1
    assert old_duplicate.reserved_size_kb == 2
    db.flush.assert_called_once()


def test_project_transfer_reprices_old_owner_duplicate_as_new_owner_increment() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, job = _reservation(
        owner_id=10,
        digest="e" * 64,
        project_id=project.id,
        reference_count=0,
        size_kb=0,
    )
    old_document = Document(
        id=uuid4(),
        sha256="e" * 64,
        original_filename="old.pdf",
        mime_type="application/pdf",
        size_bytes=2_048,
        s3_object_key="documents/old/source.pdf",
    )

    _run_transfer(
        project=project,
        active_rows=[(transferred, job)],
        old_documents=[old_document],
    )

    assert transferred.quota_owner_id == 20
    assert transferred.reserved_reference_count == 1
    assert transferred.reserved_size_kb == 2


def test_project_transfer_reprices_new_owner_duplicate_to_zero() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, job = _reservation(
        owner_id=10,
        digest="f" * 64,
        project_id=project.id,
        reference_count=1,
        size_kb=2,
    )
    new_document = Document(
        id=uuid4(),
        sha256="f" * 64,
        original_filename="new.pdf",
        mime_type="application/pdf",
        size_bytes=2_048,
        s3_object_key="documents/new/source.pdf",
    )

    _run_transfer(
        project=project,
        active_rows=[(transferred, job)],
        new_documents=[new_document],
    )

    assert transferred.quota_owner_id == 20
    assert transferred.reserved_reference_count == 0
    assert transferred.reserved_size_kb == 0


def test_project_transfer_rejects_new_owner_project_limit() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    db = MagicMock()
    db.scalar.return_value = 10

    with (
        patch("app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_entitlements",
            return_value=SimpleNamespace(
                limits=entitlements_for(SubscriptionPlan.BASIC)
            ),
        ),
        pytest.raises(AppError) as error,
    ):
        reassign_project_quota_owner(db, project=project, new_owner_id=20)

    assert error.value.code == "project_transfer_quota_exceeded"
    db.execute.assert_not_called()


def test_add_to_library_false_without_project_is_rejected() -> None:
    db = MagicMock()

    with pytest.raises(AppError) as error:
        reserve_upload(
            db,
            requester=MagicMock(id=17),
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            display_name="paper.pdf",
            source_kind="upload",
            content_sha256="a1" * 32,
            add_to_library=False,
        )

    assert error.value.code == "add_to_library_false_requires_project"
    assert error.value.kind is FailureKind.INVALID_ARGUMENT
    db.add.assert_not_called()


def test_project_upload_with_add_to_library_false_skips_library_billing() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Shared corpus", owner_id=91)
    db = MagicMock()
    db.scalar.side_effect = [None, 0, 3]
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17, project_id=project_id)
    patches = _quota_patches()

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission_for_update",
            return_value=SimpleNamespace(project=project),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._unattached_project_reservations",
            return_value=0,
        ),
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=PersistedJob(job=durable_job, created=True),
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=project_id,
            input_size_bytes=1_025,
            original_filename="shared.pdf",
            display_name="shared.pdf",
            source_kind="upload",
            content_sha256="b1" * 32,
            add_to_library=False,
        )

    job = result.reservation
    assert job.add_to_library is False
    assert job.library_quota_owner_id is None
    assert job.library_reserved_reference_count == 0
    assert job.library_reserved_size_kb == 0
    quota_lock.assert_called_once_with(db, user_id=91)


def test_owner_uploading_to_own_project_is_not_library_billed_twice() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Own project", owner_id=17)
    db = MagicMock()
    db.scalar.side_effect = [None, 0, 3]
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17, project_id=project_id)
    patches = _quota_patches()

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission_for_update",
            return_value=SimpleNamespace(project=project),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._unattached_project_reservations",
            return_value=0,
        ),
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=PersistedJob(job=durable_job, created=True),
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            origin_operation_id=uuid4(),
            correlation_id=uuid4(),
            project_id=project_id,
            input_size_bytes=1_025,
            original_filename="own.pdf",
            display_name="own.pdf",
            source_kind="upload",
            content_sha256="c1" * 32,
        )

    job = result.reservation
    assert job.quota_owner_id == 17
    assert job.library_quota_owner_id is None
    assert job.library_reserved_reference_count == 0
    assert job.library_reserved_size_kb == 0
    quota_lock.assert_called_once_with(db, user_id=17)


def test_project_transfer_preserves_library_side_billing_owner() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, transferred_job = _reservation(
        owner_id=10,
        digest="e" * 64,
        project_id=project.id,
        reference_count=1,
        size_kb=2,
        requester_id=15,
        add_to_library=True,
    )
    transferred.library_quota_owner_id = 15
    transferred.library_reserved_reference_count = 1
    transferred.library_reserved_size_kb = 2

    _run_transfer(
        project=project,
        active_rows=[(transferred, transferred_job)],
    )

    assert transferred.quota_owner_id == 20
    assert transferred.library_quota_owner_id == 15
    assert transferred.library_reserved_reference_count == 1
    assert transferred.library_reserved_size_kb == 2


def test_project_transfer_adds_old_owner_library_side_reservation() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, transferred_job = _reservation(
        owner_id=10,
        digest="f" * 64,
        project_id=project.id,
        reference_count=1,
        size_kb=2,
        requester_id=10,
        add_to_library=True,
    )

    _run_transfer(
        project=project,
        active_rows=[(transferred, transferred_job)],
    )

    assert transferred.quota_owner_id == 20
    assert transferred.reserved_reference_count == 1
    assert transferred.library_quota_owner_id == 10
    assert transferred.library_reserved_reference_count == 1
    assert transferred.library_reserved_size_kb == 2


def test_project_transfer_merges_new_owner_library_side_into_primary() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    transferred, transferred_job = _reservation(
        owner_id=10,
        digest="a" * 64,
        project_id=project.id,
        reference_count=1,
        size_kb=2,
        requester_id=20,
        add_to_library=True,
    )
    transferred.library_quota_owner_id = 20
    transferred.library_reserved_reference_count = 1
    transferred.library_reserved_size_kb = 2

    _run_transfer(
        project=project,
        active_rows=[(transferred, transferred_job)],
    )

    assert transferred.quota_owner_id == 20
    assert transferred.reserved_reference_count == 1
    assert transferred.reserved_size_kb == 2
    assert transferred.library_quota_owner_id is None
    assert transferred.library_reserved_reference_count == 0
    assert transferred.library_reserved_size_kb == 0
