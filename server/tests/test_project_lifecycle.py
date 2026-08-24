from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.bootstrap.adapters import project_repository as project_repository_module
from app.bootstrap.adapters.document_gc import ScheduledDocumentGc
from app.bootstrap.adapters.project_lifecycle import (
    ProjectDocumentCleanup,
    apply_project_deletion,
    inspect_project_deletion,
    remove_project_papers_and_schedule_gc,
    schedule_project_storage_cleanup,
)
from app.bootstrap.adapters.storage_cleanup import ScheduledStorageDeletion
from app.database.models import Document, Project
from app.modules.projects.application.lifecycle import (
    ProjectDeletionPlan,
    ProjectDeletionState,
)
from app.shared.domain import AppError


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    result.__iter__.return_value = iter(values)
    return result


def _tuples_result(values: list[tuple[object, ...]]) -> MagicMock:
    result = MagicMock()
    result.__iter__.return_value = iter(values)
    return result


def _empty_plan(project_id: object) -> ProjectDeletionPlan:
    return ProjectDeletionPlan(
        state=ProjectDeletionState(
            project_id=project_id,
            owner_id=1,
            project_updated_at=datetime.now(UTC),
            paper_association_count=0,
            research_output_count=0,
            annotation_thread_count=0,
            annotation_comment_count=0,
            annotation_revision_digest="0" * 64,
            collaborator_count=0,
            invitation_count=0,
            conversation_count=0,
            storage_object_count=0,
            active_job_count=0,
            affected_resource_digest="a" * 64,
        ),
        project_title="Project",
    )


def test_project_deletion_preserves_private_chats_and_schedules_document_gc() -> None:
    project = Project(
        id=uuid4(),
        owner_id=1,
        title="Shared corpus",
        updated_at=datetime.now(UTC),
    )
    document = Document(
        id=uuid4(),
        sha256="a" * 64,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    db = MagicMock(spec=Session)
    association_id = uuid4()
    research_item_id = uuid4()
    conversation_id = uuid4()
    db.scalar.return_value = 0
    db.scalars.side_effect = [
        _scalars_result([document.id]),
        _scalars_result([research_item_id]),
        _scalars_result([]),
        _scalars_result([conversation_id]),
    ]
    db.execute.side_effect = [
        _tuples_result([(association_id, document.id)]),
        [],
        [],
        _tuples_result([(research_item_id, f"research/audio/{research_item_id}.mp3")]),
        _tuples_result([]),
        MagicMock(),
    ]

    plan = inspect_project_deletion(db, project=project)

    assert plan.state.paper_association_count == 1
    assert plan.state.research_output_count == 1
    assert plan.state.annotation_thread_count == 0
    assert plan.state.annotation_comment_count == 0
    assert len(plan.state.annotation_revision_digest) == 64
    assert plan.state.conversation_count == 1
    assert plan.state.storage_object_count == 1
    # Inspection is mutation-free; conversation preservation is applied only
    # after a confirmation has consumed this exact plan.
    assert all(
        not str(call.args[0]).startswith("UPDATE") for call in db.execute.call_args_list
    )
    apply_project_deletion(db, project=project, plan=plan)
    assert db.execute.call_count == 6

    gc_job_id = uuid4()
    schedule_gc = MagicMock(
        return_value=ScheduledDocumentGc(job_id=gc_job_id, created=True)
    )
    operation_id = uuid4()
    correlation_id = uuid4()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_document_gc",
        schedule_gc,
    )
    cleanup_db = MagicMock(spec=Session)
    cleanup_db.execute.side_effect = [
        _tuples_result([(association_id, document.id)]),
        MagicMock(),
        _tuples_result([]),
    ]
    try:
        scheduled = remove_project_papers_and_schedule_gc(
            cleanup_db,
            project_id=project.id,
            origin_operation_id=operation_id,
            correlation_id=correlation_id,
        )
    finally:
        monkeypatch.undo()
    schedule_gc.assert_called_once_with(
        cleanup_db,
        document_id=document.id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
    )
    assert scheduled == ProjectDocumentCleanup(job_count=1, created_job_count=1)


def test_project_deletion_is_blocked_while_any_project_job_is_active() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1

    with pytest.raises(AppError) as error:
        inspect_project_deletion(
            db,
            project=Project(
                id=uuid4(),
                owner_id=1,
                title="Busy",
                updated_at=datetime.now(UTC),
            ),
        )

    assert error.value.code == "project_has_active_jobs"
    db.scalars.assert_not_called()
    db.execute.assert_not_called()


def test_project_deletion_rejects_a_foreign_storage_key_before_confirmation() -> None:
    project = Project(
        id=uuid4(),
        owner_id=1,
        title="Project",
        updated_at=datetime.now(UTC),
    )
    research_item_id = uuid4()
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.scalars.side_effect = [
        _scalars_result([]),
        _scalars_result([research_item_id]),
        _scalars_result([]),
        _scalars_result([]),
    ]
    db.execute.side_effect = [
        _tuples_result([]),
        [],
        [],
        _tuples_result([(research_item_id, "uploads/1/private/source.pdf")]),
        _tuples_result([]),
    ]

    with pytest.raises(ValueError, match="storage_delete_key_namespace_invalid"):
        inspect_project_deletion(db, project=project)


def test_storage_cleanup_is_persisted_before_project_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = tuple(
        sorted(
            (
                f"research/audio/{uuid4()}.mp3",
                f"research/audio/{uuid4()}.mp3",
            )
        )
    )
    expected = ScheduledStorageDeletion(
        job_count=2,
        created_job_count=1,
        object_count=2,
    )
    captured_keys: tuple[str, ...] = ()

    def schedule_delete(_db: Session, **kwargs: object) -> ScheduledStorageDeletion:
        nonlocal captured_keys
        captured_keys = tuple(kwargs["object_keys"])  # type: ignore[arg-type]
        return expected

    monkeypatch.setattr(
        "app.bootstrap.adapters.storage_cleanup.schedule_storage_deletion",
        schedule_delete,
    )
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [_scalars_result(list(keys)), _scalars_result([])]
    project_id = uuid4()
    operation_id = uuid4()
    correlation_id = uuid4()
    scheduled = schedule_project_storage_cleanup(
        db,
        project_id=project_id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
    )

    assert scheduled == expected
    assert captured_keys == keys
    db.commit.assert_not_called()


def test_project_deletion_receipt_includes_every_created_cleanup_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    project = Project(
        id=project_id,
        owner_id=1,
        title="Project",
        updated_at=datetime.now(UTC),
    )
    plan = _empty_plan(project_id)
    created_job_ids = (uuid4(), uuid4(), uuid4())
    storage = ScheduledStorageDeletion(
        job_count=3,
        created_job_count=2,
        object_count=3,
    )
    call_order: list[str] = []

    def apply(*_args: object, **_kwargs: object) -> None:
        call_order.append("conversations")

    def schedule_project(*_args: object, **_kwargs: object) -> object:
        call_order.append("storage")
        return storage

    def remove_papers(*_args: object, **_kwargs: object) -> ProjectDocumentCleanup:
        call_order.append("papers")
        return ProjectDocumentCleanup(job_count=2, created_job_count=1)

    monkeypatch.setattr(project_repository_module, "apply_project_deletion", apply)
    monkeypatch.setattr(
        project_repository_module,
        "remove_project_papers_and_schedule_gc",
        remove_papers,
    )
    monkeypatch.setattr(
        project_repository_module,
        "schedule_project_storage_cleanup",
        schedule_project,
    )
    monkeypatch.setattr(
        project_repository_module,
        "iter_created_cleanup_job_ids",
        MagicMock(return_value=iter(created_job_ids)),
    )
    db = MagicMock(spec=Session)
    db.get.return_value = project
    operation_id = uuid4()

    result = project_repository_module.project_repository.delete(
        db,
        project_id=project_id,
        user_id=1,
        origin_operation_id=operation_id,
        correlation_id=uuid4(),
        plan=plan,
    )

    assert result.created_job_count == 3
    assert tuple(result.created_job_ids) == created_job_ids
    assert call_order == ["storage", "papers", "conversations"]
    db.delete.assert_called_once_with(project)
