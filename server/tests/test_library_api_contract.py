from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from unittest.mock import MagicMock, call
from uuid import uuid4

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.bootstrap.adapters.library_removal import (
    delete_personal_document_annotations,
)
from app.transport.http.public_v1.documents.router import list_library_papers
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    PaperStatus,
    UploadReservation,
)
from app.main import app
from app.helpers.s3 import s3_service
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
    library_paper_response,
)
from app.modules.papers.application.contracts.documents import LibraryPaperSort
from app.modules.papers.application.library import LibraryPageDirection
from app.shared.application import Actor
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from app.modules.papers.application.contracts.tags import LibraryTagAssignmentRequest
from pydantic import ValidationError
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def _current_user() -> Actor:
    return Actor(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _executor() -> SqlAlchemyApplicationExecutor[ApplicationCapabilities]:
    return SqlAlchemyApplicationExecutor(
        MagicMock(return_value=MagicMock(spec=Session)),
        lambda session: ApplicationCapabilities(session, AppSettings()),
    )


def _entry() -> LibraryPaper:
    now = datetime.now(timezone.utc)
    document = Document(
        id=uuid4(),
        sha256="a" * 64,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
        preview_s3_key=f"documents/{'a' * 64}/preview.webp",
        title="Canonical title",
        processing_status="completed",
        created_at=now,
        updated_at=now,
    )
    entry = LibraryPaper(
        id=uuid4(),
        user_id=1,
        document_id=document.id,
        status=PaperStatus.reading.value,
        last_accessed_at=now,
        metadata_overrides={"title": "My title"},
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    entry.document = document
    entry.tags = []
    return entry


def _compiled_delete_parameters(call: object) -> tuple[str, set[object]]:
    statement = call.args[0]  # type: ignore[attr-defined]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), set(compiled.params.values())


def test_library_list_uses_empty_collection_for_new_user(monkeypatch) -> None:
    monkeypatch.setattr(
        document_repository, "list_library", lambda *_args, **_kwargs: []
    )

    response = list_library_papers(
        executor=_executor(),
        current_user=_current_user(),
    )

    assert response.items == []


def test_library_response_returns_private_signed_preview(monkeypatch) -> None:
    entry = _entry()
    monkeypatch.setattr(
        s3_service,
        "generate_presigned_url",
        lambda *_args, **_kwargs: "https://signed.example.invalid/preview",
    )

    response = library_paper_response(entry)

    assert response.library_entry_id == entry.id
    assert response.document.document_id == entry.document.id
    assert response.document.document_id == entry.document_id
    assert response.preview_url == "https://signed.example.invalid/preview"
    assert response.metadata_overrides.title == "My title"


def test_library_list_projects_one_lifecycle_row_for_an_ingesting_paper() -> None:
    entry = _entry()
    job = DurableJob(
        id=uuid4(),
        operation=JobOperation.PDF_PROCESS.value,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=entry.user_id,
        project_id=None,
        document_id=entry.document_id,
        idempotency_key=f"paper-test:{uuid4()}",
        status=JobStatus.RUNNING.value,
        progress_code="parsing",
        payload={},
        created_at=entry.created_at,
    )
    reservation = UploadReservation(
        id=job.id,
        quota_owner_id=entry.user_id,
        content_sha256=entry.document.sha256,
        display_name=entry.document.original_filename,
        source_kind="upload",
    )
    reservation.job = job
    standalone_results = MagicMock()
    standalone_results.all.return_value = []
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    reservation_results = MagicMock()
    reservation_results.all.return_value = [reservation]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.scalars.side_effect = [
        standalone_results,
        paper_results,
        reservation_results,
    ]

    page = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=entry.user_id,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=20,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert page.total_count == 1
    assert len(page.items) == 1
    assert page.items[0].entry_type == "ingestion"
    assert page.items[0].ingestion.document_id == entry.document_id
    assert len(page.positions) == 1


def test_library_list_does_not_replace_a_personal_paper_with_project_work() -> None:
    entry = _entry()
    entry.document.preview_s3_key = None
    standalone_results = MagicMock()
    standalone_results.all.return_value = []
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    reservation_results = MagicMock()
    reservation_results.all.return_value = []
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.scalars.side_effect = [
        standalone_results,
        paper_results,
        reservation_results,
    ]

    page = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=entry.user_id,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=20,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert len(page.items) == 1
    assert page.items[0].entry_type == "paper"
    reservation_statement = str(db.scalars.call_args_list[2].args[0])
    assert "jobs.project_id IS NULL" in reservation_statement


def test_library_list_includes_an_unattached_upload_reservation() -> None:
    entry = _entry()
    entry.document.preview_s3_key = None
    job = DurableJob(
        id=uuid4(),
        operation=JobOperation.PDF_PROCESS.value,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=entry.user_id,
        project_id=None,
        document_id=None,
        idempotency_key=f"paper-test:{uuid4()}",
        status=JobStatus.RUNNING.value,
        progress_code="uploading",
        payload={},
        created_at=entry.created_at,
    )
    reservation = UploadReservation(
        id=job.id,
        quota_owner_id=entry.user_id,
        content_sha256="b" * 64,
        display_name="still-processing.pdf",
        source_kind="upload",
    )
    reservation.job = job
    standalone_results = MagicMock()
    standalone_results.all.return_value = [reservation]
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    overlay_results = MagicMock()
    overlay_results.all.return_value = []
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.scalars.side_effect = [
        standalone_results,
        paper_results,
        overlay_results,
    ]

    page = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=entry.user_id,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=20,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert page.total_count == 2
    assert [item.entry_type for item in page.items] == ["ingestion", "paper"]
    assert page.items[0].ingestion.id == reservation.id
    assert page.items[0].ingestion.display_name == "still-processing.pdf"
    assert len(page.positions) == 1


def test_library_summary_counts_active_and_failed_ingestions() -> None:
    rows = MagicMock()
    rows.all.return_value = [
        (JobStatus.RUNNING.value, 2),
        (JobStatus.PENDING.value, 1),
        (JobStatus.FAILED.value, 3),
    ]
    db = MagicMock(spec=Session)
    db.execute.return_value = rows

    ingestion_count, attention_count = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).ingestion_counts(user_id=1)

    assert ingestion_count == 6
    assert attention_count == 3
    statement = str(db.execute.call_args.args[0])
    assert "upload_reservations.superseded_by_id IS NULL" in statement
    assert "jobs.project_id IS NULL" in statement


def test_library_removal_deletes_only_the_actor_personal_annotation_threads(
    monkeypatch,
) -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    delete_library_paper = MagicMock()
    personal_annotations_removed = MagicMock()
    monkeypatch.setattr(
        document_repository,
        "delete_library_paper",
        delete_library_paper,
    )

    SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(return_value=None),
        personal_annotations_removed=personal_annotations_removed,
    ).remove(
        user_id=entry.user_id,
        document_id=entry.document_id,
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )

    delete_library_paper.assert_called_once_with(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )
    personal_annotations_removed.assert_called_once_with(
        document_id=entry.document_id,
        user_id=entry.user_id,
    )


def test_personal_annotation_cleanup_excludes_project_and_other_user_data() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)

    delete_personal_document_annotations(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    sql, parameters = _compiled_delete_parameters(db.execute.call_args)
    assert "DELETE FROM scholens.research_items" in sql
    assert "research_items.kind" in sql
    assert "research_items.audience_type" in sql
    assert "research_items.created_by_id" in sql
    assert "research_items.target_document_id" in sql
    assert ResearchItemKind.ANNOTATION_THREAD.value in parameters
    assert ResearchAudienceType.PERSONAL.value in parameters
    assert ResearchAudienceType.PROJECT.value not in parameters
    assert entry.user_id in parameters
    assert entry.document_id in parameters


def test_batch_library_removal_cleans_personal_annotations_for_each_document() -> None:
    first = _entry()
    second = _entry()
    results = MagicMock()
    results.all.return_value = [first, second]
    db = MagicMock(spec=Session)
    db.scalars.return_value = results
    personal_annotations_removed = MagicMock()

    SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(return_value=None),
        personal_annotations_removed=personal_annotations_removed,
    ).remove_many(
        user_id=first.user_id,
        document_ids=(first.document_id, second.document_id),
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert personal_annotations_removed.call_args_list == [
        call(document_id=first.document_id, user_id=first.user_id),
        call(document_id=second.document_id, user_id=first.user_id),
    ]
    db.delete.assert_any_call(first)
    db.delete.assert_any_call(second)


def test_share_token_is_rotated_and_only_its_hash_is_persisted() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry

    first = document_repository.rotate_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )
    first_hash = entry.share_token_hash
    second = document_repository.rotate_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    assert first != second
    assert first_hash == hashlib.sha256(first.encode()).hexdigest()
    assert entry.share_token_hash == hashlib.sha256(second.encode()).hexdigest()
    assert second not in entry.share_token_hash
    assert entry.is_public is True


def test_revoking_share_removes_the_only_public_credential() -> None:
    entry = _entry()
    entry.is_public = True
    entry.share_token_hash = hashlib.sha256(b"token").hexdigest()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry

    document_repository.revoke_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    assert entry.is_public is False
    assert entry.share_token_hash is None


def test_library_tag_api_uses_library_document_boundaries() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/paper-ingestions/uploads" in paths
    assert "/api/v1/paper-ingestions/sources" in paths
    assert "/api/v1/paper-ingestions/urls" not in paths
    assert "/api/v1/paper-ingestions/{job_id}/retries" in paths
    assert "/api/v1/library/outputs" in paths
    assert "/api/v1/library/summary" in paths
    assert "/api/v1/library/paper-removals" in paths
    assert "/api/v1/library/tags" in paths
    assert "/api/v1/library/tags/assignments" in paths
    assert "/api/v1/library/tags/{tag_id}" in paths
    assert set(paths["/api/v1/library/tags/assignments"]) & {"put"} == {"put"}
    assert "post" not in paths["/api/v1/library/tags/assignments"]
    assert "/api/v1/library/papers/{document_id}/tags/{tag_id}" not in paths
    assert not any(path.startswith("/api/v1/paper/tag") for path in paths)
    assert not any(path.startswith("/api/v1/paper/upload") for path in paths)


def test_library_tag_assignment_is_strict_and_bounded() -> None:
    document_id = uuid4()
    tag_id = uuid4()
    request = LibraryTagAssignmentRequest(
        document_ids=[document_id],
        tag_ids=[tag_id],
    )
    assert request.document_ids == [document_id]

    clear_request = LibraryTagAssignmentRequest(
        document_ids=[document_id],
        tag_ids=[],
    )
    assert clear_request.tag_ids == []

    with pytest.raises(ValidationError):
        LibraryTagAssignmentRequest.model_validate(
            {
                "document_ids": [str(document_id), str(document_id)],
                "tag_ids": [str(tag_id)],
            }
        )
    with pytest.raises(ValidationError):
        LibraryTagAssignmentRequest.model_validate(
            {
                "document_ids": [str(document_id)],
                "tag_ids": [str(tag_id)],
                "legacy": True,
            }
        )
