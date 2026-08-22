"""PostgreSQL-only proofs for quota and administrator concurrency invariants."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import threading
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.adapters.data_repair_jobs import recover_unclaimed_pdf_job
from app.bootstrap.adapters.billing_capacity import BillingProjectCapacity
from app.bootstrap.adapters.project_repository import project_repository
from app.bootstrap.adapters.upload_reservations import reserve_upload
from app.modules.billing.application.entitlement_admin import EntitlementAdmin
from app.modules.billing.infrastructure.account_locks import (
    lock_account_resource_quota,
)
from app.modules.billing.infrastructure.application_gateway import (
    SqlAlchemySubscriptionStore,
)
from app.modules.billing.infrastructure.entitlement_admin_gateway import (
    SqlAlchemyEntitlementAdminGateway,
)
from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.modules.identity.application.contracts import SetUserBlockedRequest
from app.modules.identity.application.identity import Identity
from app.modules.identity.infrastructure.application_gateway import (
    SqlAlchemyIdentityGateway,
)
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill
from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError
from app.shared.infrastructure import SystemClock

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
            text(
                "DELETE FROM scholens.account_quota_overrides "
                "WHERE user_id = ANY(:user_ids) OR set_by_user_id = ANY(:user_ids) "
                "OR revoked_by_user_id = ANY(:user_ids)"
            ),
            {"user_ids": user_ids},
        )
        connection.execute(
            text(
                "DELETE FROM scholens.account_plan_grants "
                "WHERE user_id = ANY(:user_ids) OR granted_by_user_id = ANY(:user_ids) "
                "OR revoked_by_user_id = ANY(:user_ids)"
            ),
            {"user_ids": user_ids},
        )
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


def test_researcher_grant_reloads_target_after_concurrent_block() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-grant-race", 2)
    (admin_id, _admin_email), (target_id, target_email) = users
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE scholens.user_profiles SET is_admin = true "
                "WHERE user_id = :user_id"
            ),
            {"user_id": admin_id},
        )

    profile_locked = threading.Event()
    grant_read_started = threading.Event()
    allow_block_commit = threading.Event()

    class _SignalingGateway(SqlAlchemyEntitlementAdminGateway):
        def lock_target_identity(self, *, user_id: int) -> Actor | None:
            grant_read_started.set()
            return super().lock_target_identity(user_id=user_id)

    def block_target() -> None:
        with app_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE scholens.user_profiles SET is_blocked = true "
                    "WHERE user_id = :user_id"
                ),
                {"user_id": target_id},
            )
            profile_locked.set()
            assert allow_block_commit.wait(timeout=5)

    def grant_target() -> str:
        assert profile_locked.wait(timeout=5)
        try:
            with session_factory.begin() as db:
                identity = Identity(SqlAlchemyIdentityGateway(db), journal=MagicMock())
                actor = identity.lock_current_admin(admin_id)
                EntitlementAdmin(
                    _SignalingGateway(
                        db,
                        lock_target_identity=SqlAlchemyIdentityGateway(
                            db
                        ).lock_actor_identity,
                    ),
                    journal=MagicMock(),
                    clock=SystemClock(),
                ).grant_researcher(
                    actor=actor,
                    operation=_operation("entitlements.grant-researcher"),
                    targets=(_actor(target_id, target_email),),
                    days=365,
                    reason="concurrent eligibility proof",
                )
            return "granted"
        except AppError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            block_future = executor.submit(block_target)
            assert profile_locked.wait(timeout=5)
            grant_future = executor.submit(grant_target)
            assert grant_read_started.wait(timeout=5)
            assert not grant_future.done()
            allow_block_commit.set()
            block_future.result(timeout=5)
            assert grant_future.result(timeout=5) == "entitlement_target_ineligible"

        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.account_plan_grants "
                            "WHERE user_id = :user_id"
                        ),
                        {"user_id": target_id},
                    )
                )
                == 0
            )
    finally:
        allow_block_commit.set()
        _delete_users(admin_engine, [user_id for user_id, _ in users])
        app_engine.dispose()
        admin_engine.dispose()


def test_researcher_batch_rolls_back_when_one_live_target_is_ineligible() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-grant-batch", 3)
    (admin_id, _admin_email), first_target, second_target = users
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE scholens.user_profiles SET is_admin = true "
                "WHERE user_id = :admin_id"
            ),
            {"admin_id": admin_id},
        )
        connection.execute(
            text(
                "UPDATE scholens.user_profiles SET is_blocked = true "
                "WHERE user_id = :target_id"
            ),
            {"target_id": second_target[0]},
        )

    try:
        with pytest.raises(AppError) as error:
            with session_factory.begin() as db:
                identity = Identity(SqlAlchemyIdentityGateway(db), journal=MagicMock())
                actor = identity.lock_current_admin(admin_id)
                EntitlementAdmin(
                    SqlAlchemyEntitlementAdminGateway(
                        db,
                        lock_target_identity=SqlAlchemyIdentityGateway(
                            db
                        ).lock_actor_identity,
                    ),
                    journal=MagicMock(),
                    clock=SystemClock(),
                ).grant_researcher(
                    actor=actor,
                    operation=_operation("entitlements.grant-researcher"),
                    targets=(
                        _actor(first_target[0], first_target[1]),
                        _actor(second_target[0], second_target[1]),
                    ),
                    days=365,
                    reason="batch eligibility proof",
                )
        assert error.value.code == "entitlement_target_ineligible"
        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.account_plan_grants "
                            "WHERE user_id = ANY(:user_ids)"
                        ),
                        {"user_ids": [first_target[0], second_target[0]]},
                    )
                )
                == 0
            )
    finally:
        _delete_users(admin_engine, [user_id for user_id, _ in users])
        app_engine.dispose()
        admin_engine.dispose()


@pytest.mark.parametrize("change", ["revoke", "block"])
def test_admin_reduction_waits_for_locked_operator_authorization(change: str) -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, f"pg-operator-{change}", 3)
    (operator_id, operator_email), (reducer_id, reducer_email), target = users
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE scholens.user_profiles SET is_admin = true "
                "WHERE user_id = ANY(:user_ids)"
            ),
            {"user_ids": [operator_id, reducer_id]},
        )

    operator_authorized = threading.Event()
    reduction_started = threading.Event()
    allow_operator_commit = threading.Event()

    class _ReductionGateway(SqlAlchemyIdentityGateway):
        def lock_admin_roster(self) -> None:
            reduction_started.set()
            super().lock_admin_roster()

    def privileged_grant() -> str:
        with session_factory.begin() as db:
            identity = Identity(SqlAlchemyIdentityGateway(db), journal=MagicMock())
            actor = identity.lock_current_admin(operator_id)
            operator_authorized.set()
            assert allow_operator_commit.wait(timeout=5)
            EntitlementAdmin(
                SqlAlchemyEntitlementAdminGateway(
                    db,
                    lock_target_identity=SqlAlchemyIdentityGateway(
                        db
                    ).lock_actor_identity,
                ),
                journal=MagicMock(),
                clock=SystemClock(),
            ).grant_researcher(
                actor=actor,
                operation=_operation("entitlements.grant-researcher"),
                targets=(_actor(target[0], target[1]),),
                days=365,
                reason="operator authorization serialization",
            )
        return "granted"

    def reduce_operator() -> str:
        assert operator_authorized.wait(timeout=5)
        with session_factory.begin() as db:
            identity = Identity(_ReductionGateway(db), journal=MagicMock())
            reducer = _actor(reducer_id, reducer_email, admin=True)
            if change == "revoke":
                identity.set_admin(
                    actor=reducer,
                    operation=_operation("users.revoke-admin"),
                    user_id=operator_id,
                    enabled=False,
                )
            else:
                identity.set_blocked(
                    actor=reducer,
                    operation=_operation("users.block"),
                    user_id=operator_id,
                    request=SetUserBlockedRequest(blocked=True),
                )
        return "reduced"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            grant_future = executor.submit(privileged_grant)
            assert operator_authorized.wait(timeout=5)
            reduction_future = executor.submit(reduce_operator)
            assert reduction_started.wait(timeout=5)
            assert not reduction_future.done()
            allow_operator_commit.set()
            assert grant_future.result(timeout=5) == "granted"
            assert reduction_future.result(timeout=5) == "reduced"

        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.account_plan_grants "
                            "WHERE user_id = :user_id AND revoked_at IS NULL"
                        ),
                        {"user_id": target[0]},
                    )
                )
                == 1
            )
            operator_state = connection.execute(
                text(
                    "SELECT is_admin, is_blocked FROM scholens.user_profiles "
                    "WHERE user_id = :user_id"
                ),
                {"user_id": operator_id},
            ).one()
        assert operator_state == (
            change != "revoke",
            change == "block",
        )
    finally:
        allow_operator_commit.set()
        _delete_users(admin_engine, [user_id for user_id, _ in users])
        app_engine.dispose()
        admin_engine.dispose()


def test_paid_subscription_write_uses_the_account_capacity_lock() -> None:
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    holder_engine = create_engine(APP_DATABASE_URL)
    writer_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    holder_sessions = sessionmaker(bind=holder_engine, expire_on_commit=False)
    writer_sessions = sessionmaker(bind=writer_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-subscription-lock", 1)
    user_id, _email = users[0]
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scholens.subscriptions "
                "(id, user_id, plan, status, cancel_at_period_end) "
                "VALUES (:id, :user_id, 'basic', 'active', false)"
            ),
            {"id": uuid4(), "user_id": user_id},
        )
    lock_held = threading.Event()
    writer_lock_attempted = threading.Event()
    allow_holder_commit = threading.Event()

    @event.listens_for(writer_engine, "before_cursor_execute")
    def _observe_writer_lock(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "pg_advisory_xact_lock" in statement:
            writer_lock_attempted.set()

    def hold_capacity_lock() -> None:
        with holder_sessions.begin() as db:
            lock_account_resource_quota(db, user_id=user_id)
            lock_held.set()
            assert allow_holder_commit.wait(timeout=5)

    def save_subscription() -> str:
        assert lock_held.wait(timeout=5)
        with writer_sessions.begin() as db:
            result = SqlAlchemySubscriptionStore(db).save(
                user_id,
                plan="researcher",
                status="active",
            )
        return result.record.plan

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            holder_future = executor.submit(hold_capacity_lock)
            assert lock_held.wait(timeout=5)
            writer_future = executor.submit(save_subscription)
            assert writer_lock_attempted.wait(timeout=5)
            assert not writer_future.done()
            allow_holder_commit.set()
            holder_future.result(timeout=5)
            assert writer_future.result(timeout=5) == "researcher"

        with admin_engine.connect() as connection:
            assert (
                int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM scholens.subscriptions "
                            "WHERE user_id = :user_id AND plan = 'researcher'"
                        ),
                        {"user_id": user_id},
                    )
                )
                == 1
            )
    finally:
        allow_holder_commit.set()
        _delete_users(admin_engine, [user_id])
        holder_engine.dispose()
        writer_engine.dispose()
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


def test_unclaimed_pdf_recovery_preserves_the_supersession_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replacement reservation must exist before the source points to it."""
    assert APP_DATABASE_URL is not None and ADMIN_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(ADMIN_DATABASE_URL)
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    users = _create_users(admin_engine, "pg-pdf-recovery", 1)
    user_id, _email = users[0]
    document_id = uuid4()
    source_job_id = uuid4()
    correlation_id = uuid4()
    origin_operation_id = uuid4()
    content_sha256 = uuid4().hex * 2
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO scholens.documents
                    (id, sha256, original_filename, mime_type, size_bytes,
                     s3_object_key, processing_status, processing_job_id,
                     created_by_id)
                VALUES
                    (:document_id, :sha256, 'recovery.pdf', 'application/pdf',
                     1024, :object_key, 'processing', :source_job_id, :user_id)
                """
            ),
            {
                "document_id": document_id,
                "sha256": content_sha256,
                "object_key": f"documents/{document_id}/source.pdf",
                "source_job_id": source_job_id,
                "user_id": user_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO scholens.jobs
                    (id, operation, correlation_id, origin_operation_id,
                     requested_by_id, document_id, idempotency_key, status,
                     payload)
                VALUES
                    (:job_id, 'pdf_process', :correlation_id,
                     :origin_operation_id, :user_id, :document_id,
                     :idempotency_key, 'pending',
                     CAST(:payload AS jsonb))
                """
            ),
            {
                "job_id": source_job_id,
                "correlation_id": correlation_id,
                "origin_operation_id": origin_operation_id,
                "user_id": user_id,
                "document_id": document_id,
                "idempotency_key": f"pg-pdf-recovery:{source_job_id}",
                "payload": '{"recovery_attempt":0}',
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO scholens.upload_reservations
                    (id, quota_owner_id, reserved_size_kb,
                     reserved_reference_count, content_sha256,
                     original_filename, display_name, source_kind)
                VALUES
                    (:job_id, :user_id, 1, 1, :sha256,
                     'recovery.pdf', 'Recovery fixture', 'upload')
                """
            ),
            {
                "job_id": source_job_id,
                "user_id": user_id,
                "sha256": content_sha256,
            },
        )
    monkeypatch.setattr(
        "app.bootstrap.adapters.data_repair_jobs.get_webhook_base_url",
        lambda: "https://scholens.example.test",
    )

    try:
        with session_factory.begin() as db:
            source = db.get(DurableJob, source_job_id)
            assert source is not None
            recover_unclaimed_pdf_job(db, source)

        with admin_engine.connect() as connection:
            recovered = connection.execute(
                text(
                    """
                    SELECT source.status,
                           source.result ->> 'recovered_by_job_id'
                             AS recovered_by_job_id,
                           reservation.superseded_by_id,
                           document.processing_job_id,
                           replacement.payload ->> 'recovery_attempt'
                             AS recovery_attempt
                    FROM scholens.jobs AS source
                    JOIN scholens.upload_reservations AS reservation
                      ON reservation.id = source.id
                    JOIN scholens.documents AS document
                      ON document.id = source.document_id
                    JOIN scholens.jobs AS replacement
                      ON replacement.id = reservation.superseded_by_id
                    WHERE source.id = :job_id
                    """
                ),
                {"job_id": source_job_id},
            ).one()
        replacement_id = str(recovered.superseded_by_id)
        assert recovered.status == "failed"
        assert recovered.recovered_by_job_id == replacement_id
        assert str(recovered.processing_job_id) == replacement_id
        assert recovered.recovery_attempt == "1"
    finally:
        _delete_users(admin_engine, [user_id])
        app_engine.dispose()
        admin_engine.dispose()
