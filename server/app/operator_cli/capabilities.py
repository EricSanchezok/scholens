"""Narrow session-bound capabilities available to operator write commands."""

from __future__ import annotations

from functools import cached_property

from app.modules.billing.application.entitlement_admin import EntitlementAdmin
from app.modules.billing.infrastructure.entitlement_admin_gateway import (
    SqlAlchemyEntitlementAdminGateway,
)
from app.modules.identity.application.identity import Identity
from app.modules.identity.infrastructure.application_gateway import (
    SqlAlchemyIdentityGateway,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.infrastructure import (
    SqlAlchemyOperationJournalStore,
)
from app.bootstrap.adapters.data_repair_jobs import (
    enqueue_reprocess_job,
    recover_unclaimed_pdf_job,
)
from app.modules.papers.application.data_repair import DataRepair
from app.modules.papers.application.maintenance import (
    PassageMaintenance,
    SearchEmbeddingMaintenance,
)
from app.modules.papers.infrastructure.data_repair import SqlDataRepair
from app.modules.papers.infrastructure.passage_maintenance import SqlPassageBackfill
from app.modules.papers.infrastructure.search_embedding_maintenance import (
    SqlSearchEmbeddingBackfill,
)
from app.modules.reading_activity.application import ReadingActivityRetention
from app.modules.reading_activity.infrastructure.retention import (
    SqlReadingActivityRetention,
)
from app.shared.infrastructure import SystemClock
from sqlalchemy.orm import Session


class OperatorCapabilities:
    """Expose only application services used by the private CLI."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._clock = SystemClock()
        self._journal = OperationJournal(
            store=SqlAlchemyOperationJournalStore(session),
            clock=self._clock,
        )

    @cached_property
    def identity(self) -> Identity:
        return Identity(
            SqlAlchemyIdentityGateway(self._session),
            journal=self._journal,
        )

    @cached_property
    def entitlement_admin(self) -> EntitlementAdmin:
        identity_gateway = SqlAlchemyIdentityGateway(self._session)
        return EntitlementAdmin(
            SqlAlchemyEntitlementAdminGateway(
                self._session,
                lock_target_identity=identity_gateway.lock_actor_identity,
            ),
            journal=self._journal,
            clock=self._clock,
        )

    @cached_property
    def passage_maintenance(self) -> PassageMaintenance:
        return PassageMaintenance(
            SqlPassageBackfill(self._session),
            journal=self._journal,
        )

    @cached_property
    def search_embedding_maintenance(self) -> SearchEmbeddingMaintenance:
        return SearchEmbeddingMaintenance(
            SqlSearchEmbeddingBackfill(self._session),
            journal=self._journal,
        )

    @cached_property
    def data_repair(self) -> DataRepair:
        return DataRepair(
            SqlDataRepair(
                self._session,
                reprocess_enqueuer=enqueue_reprocess_job,
                stuck_job_recoverer=recover_unclaimed_pdf_job,
            ),
            journal=self._journal,
        )

    @cached_property
    def reading_activity_retention(self) -> ReadingActivityRetention:
        return ReadingActivityRetention(
            SqlReadingActivityRetention(self._session),
            journal=self._journal,
            clock=self._clock,
        )


def create_operator_executor() -> object:
    from app.database.database import SessionLocal
    from app.shared.infrastructure import SqlAlchemyApplicationExecutor

    return SqlAlchemyApplicationExecutor(
        SessionLocal,
        OperatorCapabilities,
    )


__all__ = ["OperatorCapabilities", "create_operator_executor"]
