"""PostgreSQL-only proofs for quota and administrator concurrency invariants."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import threading
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.adapters.billing_capacity import BillingProjectCapacity
from app.bootstrap.adapters.project_repository import project_repository
from app.bootstrap.adapters.upload_reservations import reserve_upload
from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.modules.identity.application.contracts import SetUserBlockedRequest
from app.modules.identity.application.identity import Identity
from app.modules.identity.infrastructure.application_gateway import (
    SqlAlchemyIdentityGateway,
)
from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill
from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError

APP_DATABASE_URL = os.getenv("SCHOLENS_POSTGRES_TEST_URL")
ADMIN_DATABASE_URL = os.getenv("SCHOLENS_POSTGRES_TEST_ADMIN_URL")
pytestmark = pytest.mark.skipif(
    not APP_DATABASE_URL or not ADMIN_DATABASE_URL,
    reason="isolated PostgreSQL URLs are not configured",
)


def _operation(command: str):
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=CliOrigin(command, uuid4()),
        credential=None,
    )


def _actor(user_id: int, email: str, *, admin: bool = False) -> Actor:
    return Actor(
        id=user_id,
        email=email,
        display_name=None,
        status="active",
        email_verified=True,
        is_admin=admin,
    )


def _create_users(admin_engine, prefix: str, count: int) -> list[tuple[int, str]]:
    users: list[tuple[int, str]] = []
    with admin_engine.begin() as connection:
        for index in range(count):
            email = f"{prefix}-{index}-{uuid4().hex}@example.com"
            user_id = int(
                connection.scalar(
                    text(
                        """
                        INSERT INTO auth.users
                            (email, password_hash, status, email_verified_at)
                        VALUES (:email, 'fixture', 'active', now())
                        RETURNING id
                        """
                    ),
                    {"email": email},
                )
            )
            connection.execute(
                text("INSERT INTO scholens.user_profiles (user_id) VALUES (:user_id)"),
                {"user_id": user_id},
            )
            users.append((user_id, email))
    return users


def _delete_users(admin_engine, user_ids: list[int]) -> None:
    with admin_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM scholens.jobs WHERE requested_by_id = ANY(:user_ids)"),
            {"user_ids": user_ids},
        )
        connection.execute(
            text("DELETE FROM scholens.projects WHERE owner_id = ANY(:user_ids)"),
            {"user_ids": user_ids},
        )
        connection.execute(
            text("DELETE FROM scholens.documents WHERE created_by_id = ANY(:user_ids)"),
            {"user_ids": user_ids},
        )
        connection.execute(
            text("DELETE FROM scholens.user_profiles WHERE user_id = ANY(:user_ids)"),
            {"user_ids": user_ids},
        )
        connection.execute(
            text("DELETE FROM auth.users WHERE id = ANY(:user_ids)"),
            {"user_ids": user_ids},
        )


def test_unique_usage_union_releases_only_after_the_last_owned_reference() -> None:
    assert ADMIN_DATABASE_URL is not None
    engine = create_engine(ADMIN_DATABASE_URL)
    owner_id = 9_000_001
    collaborator_id = 9_000_002
    document_ids = [uuid4() for _ in range(4)]
    project_ids = [uuid4() for _ in range(3)]
    transaction_connection = engine.connect()
    transaction = transaction_connection.begin()
    db = Session(bind=transaction_connection)
    try:
        transaction_connection.execute(
            text(
                """
                INSERT INTO auth.users
                    (id, email, password_hash, status, email_verified_at)
                VALUES
                    (:owner_id, :owner_email, 'fixture', 'active', now()),
                    (:collaborator_id, :collaborator_email, 'fixture', 'active', now())
                """
            ),
            {
                "owner_id": owner_id,
                "owner_email": f"pg-quota-{uuid4().hex}@example.com",
                "collaborator_id": collaborator_id,
                "collaborator_email": f"pg-collaborator-{uuid4().hex}@example.com",
            },
        )
        for index, (document_id, size_bytes) in enumerate(
            zip(document_ids, (1_024, 2_048, 3_072, 4_096), strict=True)
        ):
            transaction_connection.execute(
                text(
                    """
                    INSERT INTO scholens.documents
                        (id, sha256, original_filename, mime_type, size_bytes,
                         s3_object_key, processing_status, created_by_id)
                    VALUES
                        (:id, :sha, :filename, 'application/pdf', :size,
                         :object_key, 'completed', :owner_id)
                    """
                ),
                {
                    "id": document_id,
                    "sha": f"{index + 1:064x}",
                    "filename": f"document-{index}.pdf",
                    "size": size_bytes,
                    "object_key": f"documents/{document_id}/source.pdf",
                    "owner_id": owner_id,
                },
            )
        transaction_connection.execute(
            text(
                """
                INSERT INTO scholens.projects (id, title, owner_id) VALUES
                    (:first, 'First', :owner),
                    (:second, 'Second', :owner),
                    (:shared, 'Collaborator-owned', :collaborator)
                """
            ),
            {
                "first": project_ids[0],
                "second": project_ids[1],
                "shared": project_ids[2],
                "owner": owner_id,
                "collaborator": collaborator_id,
            },
        )
        library_id = uuid4()
        project_paper_ids = [uuid4() for _ in range(6)]
        transaction_connection.execute(
            text(
                """
                INSERT INTO scholens.library_papers (id, user_id, document_id)
                VALUES (:id, :owner, :document)
                """
            ),
            {"id": library_id, "owner": owner_id, "document": document_ids[2]},
        )
        associations = (
            (project_ids[0], document_ids[0]),
            (project_ids[0], document_ids[1]),
            (project_ids[1], document_ids[1]),
            (project_ids[1], document_ids[2]),
            (project_ids[2], document_ids[3]),
            (project_ids[2], document_ids[1]),
        )
        for association_id, (project_id, document_id) in zip(
            project_paper_ids, associations, strict=True
        ):
            transaction_connection.execute(
                text(
                    """
                    INSERT INTO scholens.project_papers
                        (id, project_id, document_id, added_by_id)
                    VALUES (:id, :project, :document, :owner)
                    """
                ),
                {
                    "id": association_id,
                    "project": project_id,
                    "document": document_id,
                    "owner": owner_id,
                },
            )

        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 3
        )
        assert resource_usage_repository.completed_storage_kb(db, user_id=owner_id) == 6
        assert (
            resource_usage_repository.completed_reference_count(
                db, user_id=collaborator_id
            )
            == 2
        )
        old_after_transfer = resource_usage_repository.completed_documents(
            db,
            user_id=owner_id,
            exclude_project_id=project_ids[0],
        )
        new_after_transfer = resource_usage_repository.completed_documents(
            db,
            user_id=collaborator_id,
            include_project_id=project_ids[0],
        )
        assert {document.id for document in old_after_transfer} == {
            document_ids[1],
            document_ids[2],
        }
        assert {document.id for document in new_after_transfer} == {
            document_ids[0],
            document_ids[1],
            document_ids[3],
        }

        transaction_connection.execute(
            text("DELETE FROM scholens.library_papers WHERE id = :id"),
            {"id": library_id},
        )
        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 3
        )
        transaction_connection.execute(
            text("DELETE FROM scholens.project_papers WHERE id = :id"),
            {"id": project_paper_ids[3]},
        )
        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 2
        )
        assert resource_usage_repository.completed_storage_kb(db, user_id=owner_id) == 3

        transaction_connection.execute(
            text("DELETE FROM scholens.project_papers WHERE id = :id"),
            {"id": project_paper_ids[0]},
        )
        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 1
        )
        transaction_connection.execute(
            text("DELETE FROM scholens.project_papers WHERE id = :id"),
            {"id": project_paper_ids[1]},
        )
        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 1
        )
        assert resource_usage_repository.completed_storage_kb(db, user_id=owner_id) == 2
        transaction_connection.execute(
            text("DELETE FROM scholens.project_papers WHERE id = :id"),
            {"id": project_paper_ids[2]},
        )
        assert (
            resource_usage_repository.completed_reference_count(db, user_id=owner_id)
            == 0
        )
    finally:
        db.close()
        transaction.rollback()
        transaction_connection.close()
        engine.dispose()


def test_concurrent_same_digest_upload_reserves_account_capacity_once() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-upload", 1)
    user_id, email = users[0]
    barrier = threading.Barrier(2)

    def upload() -> str:
        try:
            with session_factory.begin() as db:
                barrier.wait()
                reserve_upload(
                    db,
                    requester=_actor(user_id, email),
                    origin_operation_id=uuid4(),
                    correlation_id=uuid4(),
                    project_id=None,
                    input_size_bytes=2_048,
                    original_filename="same.pdf",
                    display_name="same.pdf",
                    source_kind="upload",
                    content_sha256="a" * 64,
                )
            return "created"
        except AppError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: upload(), range(2)))
        assert sorted(outcomes) == ["created", "document_upload_in_progress"]
        with admin_engine.connect() as connection:
            assert connection.execute(
                text(
                    """
                    SELECT COUNT(*), SUM(reserved_reference_count),
                           SUM(reserved_size_kb)
                    FROM scholens.upload_reservations
                    WHERE quota_owner_id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).one() == (1, 1, 2)
    finally:
        _delete_users(admin_engine, [user_id])
        app_engine.dispose()
        admin_engine.dispose()


def test_concurrent_project_creation_cannot_cross_basic_limit() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-project", 1)
    user_id, email = users[0]
    with admin_engine.begin() as connection:
        for index in range(9):
            connection.execute(
                text(
                    "INSERT INTO scholens.projects (id, title, owner_id) "
                    "VALUES (:id, :title, :owner_id)"
                ),
                {"id": uuid4(), "title": f"Existing {index}", "owner_id": user_id},
            )
    barrier = threading.Barrier(2)

    def create_project(index: int) -> str:
        try:
            with session_factory.begin() as db:
                barrier.wait()
                actor = _actor(user_id, email)
                BillingProjectCapacity(db).require_create(actor=actor)
                project_repository.create(
                    db,
                    owner_id=user_id,
                    title=f"Concurrent {index}",
                    description=None,
                )
            return "created"
        except AppError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(create_project, range(2)))
        assert sorted(outcomes) == ["created", "project_quota_exceeded"]
        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.projects "
                            "WHERE owner_id = :owner_id"
                        ),
                        {"owner_id": user_id},
                    )
                )
                == 10
            )
    finally:
        _delete_users(admin_engine, [user_id])
        app_engine.dispose()
        admin_engine.dispose()


def test_concurrent_first_admin_bootstrap_creates_exactly_one_admin() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-bootstrap", 2)
    barrier = threading.Barrier(2)

    def bootstrap(user: tuple[int, str]) -> str:
        user_id, _email = user
        try:
            with session_factory.begin() as db:
                barrier.wait()
                Identity(
                    SqlAlchemyIdentityGateway(db),
                    journal=MagicMock(),
                ).bootstrap_admin(
                    operation=_operation("users.bootstrap-admin"),
                    user_id=user_id,
                )
            return "created"
        except AppError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(bootstrap, users))
        assert sorted(outcomes) == ["admin_bootstrap_closed", "created"]
        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.user_profiles "
                            "WHERE user_id = ANY(:user_ids) AND is_admin"
                        ),
                        {"user_ids": [user_id for user_id, _ in users]},
                    )
                )
                == 1
            )
    finally:
        _delete_users(admin_engine, [user_id for user_id, _ in users])
        app_engine.dispose()
        admin_engine.dispose()


@pytest.mark.parametrize("change", ["revoke", "block"])
def test_concurrent_admin_reduction_preserves_one_available_admin(change: str) -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, f"pg-{change}", 2)
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE scholens.user_profiles SET is_admin = true "
                "WHERE user_id = ANY(:user_ids)"
            ),
            {"user_ids": [user_id for user_id, _ in users]},
        )
    barrier = threading.Barrier(2)

    def reduce(pair: tuple[tuple[int, str], tuple[int, str]]) -> str:
        actor_user, target_user = pair
        try:
            with session_factory.begin() as db:
                barrier.wait()
                identity = Identity(
                    SqlAlchemyIdentityGateway(db),
                    journal=MagicMock(),
                )
                actor = _actor(actor_user[0], actor_user[1], admin=True)
                if change == "revoke":
                    identity.set_admin(
                        actor=actor,
                        operation=_operation("users.revoke-admin"),
                        user_id=target_user[0],
                        enabled=False,
                    )
                else:
                    identity.set_blocked(
                        actor=actor,
                        operation=_operation("users.block"),
                        user_id=target_user[0],
                        request=SetUserBlockedRequest(blocked=True),
                    )
            return "changed"
        except AppError as error:
            return error.code

    pairs = [(users[0], users[1]), (users[1], users[0])]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reduce, pairs))
        assert sorted(outcomes) == ["changed", "last_admin_required"]
        with admin_engine.connect() as connection:
            available = int(
                connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM scholens.user_profiles AS profile
                        JOIN auth.users AS identity ON identity.id = profile.user_id
                        WHERE profile.user_id = ANY(:user_ids)
                          AND profile.is_admin AND NOT profile.is_blocked
                          AND identity.status = 'active'
                          AND identity.email_verified_at IS NOT NULL
                        """
                    ),
                    {"user_ids": [user_id for user_id, _ in users]},
                )
            )
        assert available == 1
    finally:
        _delete_users(admin_engine, [user_id for user_id, _ in users])
        app_engine.dispose()
        admin_engine.dispose()


def test_runtime_role_can_backfill_passages_without_trigger_ddl() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-backfill", 1)
    user_id, _email = users[0]
    document_id = uuid4()
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO scholens.documents
                    (id, sha256, original_filename, mime_type, size_bytes,
                     s3_object_key, raw_content, processing_status, created_by_id)
                VALUES
                    (:id, :sha, 'backfill.pdf', 'application/pdf', 1024,
                     :key, 'alpha beta', 'completed', :user_id)
                """
            ),
            {
                "id": document_id,
                "sha": uuid4().hex * 2,
                "key": f"documents/{document_id}/source.pdf",
                "user_id": user_id,
            },
        )
    try:
        with session_factory.begin() as db:
            result = SqlPassageBackfill(db).backfill(batch_size=1, apply=True)
        assert result.indexed_documents == 1
        with admin_engine.connect() as connection:
            assert bool(
                connection.scalar(
                    text(
                        "SELECT ts_vector IS NOT NULL "
                        "FROM scholens.document_passages "
                        "WHERE document_id = :document_id"
                    ),
                    {"document_id": document_id},
                )
            )
    finally:
        _delete_users(admin_engine, [user_id])
        app_engine.dispose()
        admin_engine.dispose()
