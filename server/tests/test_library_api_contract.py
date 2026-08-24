from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, load_only

from app.bootstrap.adapters.library_removal import (
    delete_personal_document_annotations,
)
from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.settings import AppSettings
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    PaperStatus,
    UploadReservation,
)
from app.helpers.s3 import s3_service
from app.main import app
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    DocumentResponse,
    LibraryPaperSort,
)
from app.modules.papers.application.contracts.tags import LibraryTagAssignmentRequest
from app.modules.papers.application.library import LibraryPageDirection
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
    DOCUMENT_RESPONSE_COLUMNS,
)
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
    library_paper_response,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from app.transport.http.public_v1.documents.router import list_library_papers


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


def _streaming_rows(rows: Iterable[tuple[object, ...]]) -> MagicMock:
    tuples = MagicMock()
    tuples.__iter__.return_value = iter(rows)
    tuples.all.side_effect = AssertionError("confirmation scan must stay streaming")
    result = MagicMock()
    result.tuples.return_value = tuples
    return result


def _postgres_sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


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


def test_library_metadata_override_lists_match_existing_runtime_bounds() -> None:
    value = DocumentMetadataOverrides(
        authors=["  Ada Lovelace  "],
        institutions=["A" * 500],
    )

    assert value.authors == ["Ada Lovelace"]
    assert value.institutions == ["A" * 500]
    for field in ("authors", "institutions"):
        with pytest.raises(ValidationError):
            DocumentMetadataOverrides.model_validate({field: [""]})
        with pytest.raises(ValidationError):
            DocumentMetadataOverrides.model_validate({field: ["A" * 501]})
        item_schema = DocumentMetadataOverrides.model_json_schema()["properties"][
            field
        ]["anyOf"][0]["items"]
        assert item_schema["minLength"] == 1
        assert item_schema["maxLength"] == 500


def test_document_response_column_profile_excludes_canonical_content() -> None:
    expected_columns = {
        "id" if name == "document_id" else name
        for name in DocumentResponse.model_fields
    }

    assert {column.key for column in DOCUMENT_RESPONSE_COLUMNS} == expected_columns
    statement = select(Document).options(
        load_only(*DOCUMENT_RESPONSE_COLUMNS, raiseload=True)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "documents.raw_content" not in sql
    assert "documents.page_offset_map" not in sql
    assert "documents.parser_markdown_s3_key" not in sql


def test_document_access_uses_minimal_strict_document_loader() -> None:
    document = _entry().document
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [None, uuid4(), document]

    access = get_document_access(
        db,
        document_id=document.id,
        user_id=7,
    )

    assert access is not None
    document_statement = db.scalar.call_args_list[2].args[0]
    sql = str(document_statement.compile(dialect=postgresql.dialect()))
    assert "documents.id" in sql
    assert "documents.title" in sql
    assert "documents.raw_content" not in sql
    assert "documents.page_offset_map" not in sql
    assert "documents.summary" not in sql


def test_find_accessible_uses_complete_metadata_without_content_columns() -> None:
    document = _entry().document
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [None, uuid4(), document]

    result = document_repository.find_accessible(
        db,
        document_id=document.id,
        user=_current_user(),
    )

    assert result is document
    document_statement = db.scalar.call_args_list[2].args[0]
    sql = str(document_statement.compile(dialect=postgresql.dialect()))
    assert all(f"documents.{column.key}" in sql for column in DOCUMENT_RESPONSE_COLUMNS)
    assert "documents.raw_content" not in sql
    assert "documents.page_offset_map" not in sql


def test_require_library_paper_uses_strict_document_metadata_loader() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry

    result = document_repository.require_library_paper_by_document(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    assert result is entry
    statement = db.scalar.call_args.args[0]
    document_contexts = [
        context
        for option in statement._with_options
        for context in option.context
        if "LibraryPaper.document" in str(context.path)
    ]
    loaded_columns = {
        context.path[-1].key
        for context in document_contexts
        if getattr(context.path[-1], "key", None) is not None
        and context.strategy == (("deferred", False), ("instrument", True))
    }
    assert loaded_columns == {
        column.key for column in DOCUMENT_LIBRARY_RESPONSE_COLUMNS
    }
    assert any(("raiseload", True) in context.strategy for context in document_contexts)


@pytest.mark.parametrize(
    ("include_active_ingestions", "limit"),
    [(True, 100), (False, 5)],
)
def test_library_list_uses_strict_document_metadata_loader(
    *, include_active_ingestions: bool, limit: int
) -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    id_results = MagicMock()
    id_results.all.return_value = [uuid4()]
    hydrated_results = MagicMock()
    hydrated_results.all.return_value = []
    db.scalars.side_effect = [id_results, hydrated_results]

    SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=limit,
        direction=LibraryPageDirection.FORWARD,
        position=None,
        include_active_ingestions=include_active_ingestions,
    )

    paper_statement = next(
        call.args[0] for call in db.scalars.call_args_list if call.args[0]._with_options
    )
    document_contexts = [
        context
        for option in paper_statement._with_options
        for context in option.context
        if "LibraryPaper.document" in str(context.path)
    ]
    loaded_columns = {
        context.path[-1].key
        for context in document_contexts
        if getattr(context.path[-1], "key", None) is not None
        and context.strategy == (("deferred", False), ("instrument", True))
    }
    assert loaded_columns == {
        column.key for column in DOCUMENT_LIBRARY_RESPONSE_COLUMNS
    }
    assert any(("raiseload", True) in context.strategy for context in document_contexts)


def test_library_confirmation_plan_excludes_signed_preview_and_binds_share_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    entry.is_public = True
    entry.share_token_hash = "b" * 64
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry
    signing = MagicMock(side_effect=RuntimeError("signing must not run"))
    monkeypatch.setattr(s3_service, "generate_presigned_url", signing)

    plan = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).confirmation_plan(user_id=entry.user_id, document_id=entry.document_id)

    assert plan.state.library_entry_id == entry.id
    assert plan.state.document_id == entry.document_id
    assert plan.state.is_public is True
    assert plan.state.share_token_hash == "b" * 64
    assert "preview" not in plan.state.model_dump(mode="json")
    signing.assert_not_called()


def test_library_removal_plan_counts_and_digests_personal_annotation_cascade() -> None:
    entry = _entry()
    now = datetime.now(timezone.utc)
    thread_id = uuid4()
    first_comment_id = uuid4()
    second_comment_id = uuid4()
    documents = MagicMock()
    documents.all.return_value = [entry.document_id]
    entries = MagicMock()
    entries.all.return_value = [entry]
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [documents, entries]
    db.execute.side_effect = [
        _streaming_rows([(entry.document_id, thread_id, now)]),
        _streaming_rows([(entry.document_id, thread_id, now)]),
        _streaming_rows(
            [
                (entry.document_id, thread_id, first_comment_id, now),
                (entry.document_id, thread_id, second_comment_id, now),
            ]
        ),
    ]

    plan = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).removal_plan(
        user_id=entry.user_id,
        document_ids=(entry.document_id,),
    )

    item = plan.state.items[0]
    assert item.personal_annotation_thread_count == 1
    assert item.personal_annotation_comment_count == 2
    assert len(item.personal_annotation_digest) == 64
    lock_statements = [
        _postgres_sql(invocation.args[0]) for invocation in db.scalars.call_args_list
    ] + [_postgres_sql(invocation.args[0]) for invocation in db.execute.call_args_list]
    assert "FOR UPDATE OF documents" in lock_statements[0]
    assert "ORDER BY scholens.documents.id" in lock_statements[0]
    assert "FOR UPDATE OF library_papers" in lock_statements[1]
    assert "ORDER BY scholens.library_papers.id" in lock_statements[1]
    assert "FOR UPDATE OF research_items" in lock_statements[2]
    assert "FOR UPDATE OF annotation_threads" in lock_statements[3]
    assert "FOR UPDATE OF annotation_comments" in lock_statements[4]
    assert all(
        invocation.args[0].get_execution_options().get("yield_per") == 100
        for invocation in db.execute.call_args_list
    )


def test_library_removal_plan_streams_a_large_comment_revision_set() -> None:
    entry = _entry()
    now = datetime.now(timezone.utc)
    thread_id = uuid4()
    documents = MagicMock()
    documents.all.return_value = [entry.document_id]
    entries = MagicMock()
    entries.all.return_value = [entry]
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [documents, entries]
    db.execute.side_effect = [
        _streaming_rows([(entry.document_id, thread_id, now)]),
        _streaming_rows([(entry.document_id, thread_id, now)]),
        _streaming_rows(
            (
                (entry.document_id, thread_id, UUID(int=index + 1), now)
                for index in range(10_000)
            )
        ),
    ]

    plan = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).removal_plan(
        user_id=entry.user_id,
        document_ids=(entry.document_id,),
    )

    item = plan.state.items[0]
    assert item.personal_annotation_thread_count == 1
    assert item.personal_annotation_comment_count == 10_000
    assert len(plan.state.model_dump_json().encode("utf-8")) < 1_000
    comment_sql = _postgres_sql(db.execute.call_args_list[2].args[0])
    assert "annotation_comments.content" not in comment_sql


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
    id_results = MagicMock()
    id_results.all.return_value = [entry.id]
    reservation_results = MagicMock()
    reservation_results.all.return_value = [reservation]
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [0, 1]
    db.execute.return_value = standalone_results
    db.scalars.side_effect = [
        id_results,
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


def test_bounded_library_summary_scope_never_overlays_active_ingestions() -> None:
    entry = _entry()
    entry.document.preview_s3_key = None
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    id_results = MagicMock()
    id_results.all.return_value = [entry.id]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.scalars.side_effect = [id_results, paper_results]

    page = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=entry.user_id,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
        include_active_ingestions=False,
    )

    assert page.total_count == 1
    assert [item.entry_type for item in page.items] == ["paper"]
    assert db.scalars.call_count == 2


def test_library_list_does_not_replace_a_personal_paper_with_project_work() -> None:
    entry = _entry()
    entry.document.preview_s3_key = None
    standalone_results = MagicMock()
    standalone_results.all.return_value = []
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    id_results = MagicMock()
    id_results.all.return_value = [entry.id]
    reservation_results = MagicMock()
    reservation_results.all.return_value = []
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [0, 1]
    db.execute.return_value = standalone_results
    db.scalars.side_effect = [
        id_results,
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


def test_library_list_applies_literal_like_pattern_to_every_search_path() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []
    db.scalars.return_value.all.return_value = []

    SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=7,
        query="100%_\\",
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=20,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    statements = [
        *(call.args[0] for call in db.scalar.call_args_list),
        *(call.args[0] for call in db.execute.call_args_list),
        *(call.args[0] for call in db.scalars.call_args_list),
    ]
    assert len(statements) == 4
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.count(" LIKE ") == sql.count(" ESCAPE '\\\\'")
        assert "%100\\%\\_\\\\%" in compiled.params.values()


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
    standalone_results.all.return_value = [
        SimpleNamespace(
            job_id=job.id,
            display_name=reservation.display_name,
            source_kind=reservation.source_kind,
            status=job.status,
            progress_code=job.progress_code,
            project_id=job.project_id,
            document_id=job.document_id,
            error_code=job.error_code,
            created_at=job.created_at,
        )
    ]
    paper_results = MagicMock()
    paper_results.all.return_value = [entry]
    id_results = MagicMock()
    id_results.all.return_value = [entry.id]
    overlay_results = MagicMock()
    overlay_results.all.return_value = []
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [1, 1]
    db.execute.return_value = standalone_results
    db.scalars.side_effect = [
        id_results,
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
    assert len(page.positions) == 2


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


def test_library_removal_deletes_only_the_actor_personal_annotation_threads() -> None:
    entry = _entry()
    documents = MagicMock()
    documents.all.return_value = [entry.document_id]
    entries = MagicMock()
    entries.all.return_value = [entry]
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [documents, entries]
    personal_annotations_removed = MagicMock()

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

    personal_annotations_removed.assert_called_once_with(
        document_id=entry.document_id,
        user_id=entry.user_id,
    )
    db.delete.assert_called_once_with(entry)
    lock_statements = [
        _postgres_sql(invocation.args[0]) for invocation in db.scalars.call_args_list
    ]
    assert "FOR UPDATE OF documents" in lock_statements[0]
    assert "FOR UPDATE OF library_papers" in lock_statements[1]


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
    documents = MagicMock()
    documents.all.return_value = sorted([first.document_id, second.document_id])
    entries = MagicMock()
    entries.all.return_value = [first, second]
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [documents, entries]
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
    lock_statements = [
        _postgres_sql(invocation.args[0]) for invocation in db.scalars.call_args_list
    ]
    assert "FOR UPDATE OF documents" in lock_statements[0]
    assert "ORDER BY scholens.documents.id" in lock_statements[0]
    assert "FOR UPDATE OF library_papers" in lock_statements[1]
    assert "ORDER BY scholens.library_papers.id" in lock_statements[1]


def test_share_token_is_rotated_and_only_its_hash_is_persisted() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [entry.id, entry.id]

    first = document_repository.rotate_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )
    second = document_repository.rotate_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    assert first != second
    first_update = db.execute.call_args_list[0].args[0]
    second_update = db.execute.call_args_list[1].args[0]
    assert (
        hashlib.sha256(first.encode()).hexdigest()
        in first_update.compile().params.values()
    )
    assert (
        hashlib.sha256(second.encode()).hexdigest()
        in second_update.compile().params.values()
    )
    assert first not in first_update.compile().params.values()
    assert second not in second_update.compile().params.values()
    first_lock_sql = _postgres_sql(db.scalar.call_args_list[0].args[0])
    assert "documents" not in first_lock_sql
    assert first_lock_sql.endswith("FOR UPDATE")


def test_revoking_share_removes_the_only_public_credential() -> None:
    entry = _entry()
    entry.is_public = True
    entry.share_token_hash = hashlib.sha256(b"token").hexdigest()
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [entry.id, entry.id]

    changed = document_repository.revoke_public_share(
        db,
        document_id=entry.document_id,
        user_id=entry.user_id,
    )

    assert changed is True
    lock_sql = _postgres_sql(db.scalar.call_args_list[0].args[0])
    assert "documents" not in lock_sql
    assert lock_sql.endswith("FOR UPDATE")
    revoke_sql = _postgres_sql(db.scalar.call_args_list[1].args[0])
    assert "UPDATE scholens.library_papers" in revoke_sql
    assert "RETURNING scholens.library_papers.id" in revoke_sql


def test_public_share_resolution_locks_membership_until_collection_finishes() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry.document_id

    document_id = document_repository.require_public_share_document_id(
        db,
        token="public-token",
    )

    assert document_id == entry.document_id
    sql = _postgres_sql(db.scalar.call_args.args[0])
    assert "documents" not in sql
    assert "FOR UPDATE OF library_papers" in sql


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
