"""Table-driven contracts for framework-free business decisions."""

from __future__ import annotations

import pytest

from app.modules.billing.domain import (
    AccountCapacityFacts,
    PlanGrantFacts,
    SubscriptionFacts,
    effective_plan,
    entitlements_for,
    require_account_document_capacity,
    require_project_paper_capacity,
    resolve_entitlements,
)
from app.modules.identity.domain import (
    AccountAccessFacts,
    require_administrator,
    require_product_access,
)
from app.modules.integrations.zotero.domain import (
    ImportReservationAction,
    ImportReservationFacts,
    canonical_import_payload,
    decide_import_reservation,
)
from app.modules.jobs.domain import (
    can_claim_job,
    can_complete_job,
    can_fail_job,
    can_heartbeat_job,
    is_terminal_job,
)
from app.modules.conversations.domain import (
    ConversationAccessFacts,
    evaluate_conversation_access,
)
from app.modules.projects.domain import (
    ProjectAccessFacts,
    ProjectPermission,
    ProjectPermissions,
    require_grant_subset,
    require_permission,
)
from app.modules.papers.domain import (
    can_begin_processing,
    can_complete_processing,
    can_fail_processing,
    classify_document_access,
    durable_ingestion_key,
    normalize_idempotency_key,
)
from app.modules.research.domain import (
    ResearchAccessFacts,
    evaluate_research_access,
    require_research_manager,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import (
    ConversationScopeType,
    DocumentProcessingStatus,
    JobStatus,
    ResearchAudienceType,
    SubscriptionPlan,
    SubscriptionStatus,
)
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def test_effective_plan_requires_an_active_unexpired_subscription() -> None:
    now = datetime.now(UTC)
    active = SubscriptionFacts(
        SubscriptionPlan.RESEARCHER,
        SubscriptionStatus.ACTIVE,
        now + timedelta(days=1),
    )
    expired = SubscriptionFacts(
        SubscriptionPlan.RESEARCHER,
        SubscriptionStatus.ACTIVE,
        now - timedelta(seconds=1),
    )
    assert effective_plan(active, now=now) is SubscriptionPlan.RESEARCHER
    assert effective_plan(expired, now=now) is SubscriptionPlan.BASIC


def test_product_plan_limits_match_the_promotional_capacity_contract() -> None:
    basic = entitlements_for(SubscriptionPlan.BASIC)
    researcher = entitlements_for(SubscriptionPlan.RESEARCHER)

    assert basic.as_limits() == {
        "paper_uploads": 300,
        "knowledge_base_size_kb": 5 * 1024 * 1024,
        "token_credits_weekly": 30_000_000,
        "projects": 10,
        "project_papers": 300,
    }
    assert basic.zotero_auto_sync is False
    assert researcher.as_limits() == {
        "paper_uploads": 5_000,
        "knowledge_base_size_kb": 100 * 1024 * 1024,
        "token_credits_weekly": 300_000_000,
        "projects": 100,
        "project_papers": 5_000,
    }
    assert researcher.zotero_auto_sync is True


def test_paid_and_granted_researcher_are_resolved_independently() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    active_paid = SubscriptionFacts(
        SubscriptionPlan.RESEARCHER,
        SubscriptionStatus.ACTIVE,
        now + timedelta(days=1),
    )
    active_grant = PlanGrantFacts(
        SubscriptionPlan.RESEARCHER,
        now + timedelta(days=365),
    )
    expired_grant = PlanGrantFacts(
        SubscriptionPlan.RESEARCHER,
        now,
    )

    paid = resolve_entitlements(active_paid, grant=active_grant, now=now)
    granted = resolve_entitlements(None, grant=active_grant, now=now)
    expired = resolve_entitlements(None, grant=expired_grant, now=now)

    assert paid.plan is SubscriptionPlan.RESEARCHER
    assert paid.source == "subscription"
    assert granted.plan is SubscriptionPlan.RESEARCHER
    assert granted.source == "grant"
    assert granted.grant_expires_at == active_grant.expires_at
    assert expired.plan is SubscriptionPlan.BASIC
    assert expired.source == "basic"


def test_quota_overrides_replace_individual_limits_and_allow_zero() -> None:
    resolution = resolve_entitlements(
        None,
        now=datetime(2026, 8, 16, tzinfo=UTC),
        overrides={"paper_uploads": 0, "token_credits_weekly": 42},
    )

    assert resolution.limits.paper_uploads == 0
    assert resolution.limits.token_credits_weekly == 42
    assert resolution.limits.projects == 10


def test_billing_domain_enforces_account_and_project_capacity() -> None:
    basic = entitlements_for(SubscriptionPlan.BASIC)
    with pytest.raises(AppError) as account_error:
        require_account_document_capacity(
            SubscriptionPlan.BASIC,
            AccountCapacityFacts(
                current_documents=basic.paper_uploads,
                current_storage_kb=0,
                added_documents=1,
                added_storage_kb=1,
            ),
        )
    assert account_error.value.code == "paper_quota_exceeded"

    with pytest.raises(AppError) as project_error:
        require_project_paper_capacity(
            SubscriptionPlan.BASIC,
            current_documents=basic.project_papers,
            added_documents=1,
        )
    assert project_error.value.code == "project_paper_quota_exceeded"


def test_paper_domain_normalizes_identity_and_access_rules() -> None:
    project_id = uuid4()
    assert normalize_idempotency_key(" request-1 ") == "request-1"
    assert (
        durable_ingestion_key(
            actor_id=7,
            project_id=project_id,
            idempotency_key="request-1",
        )
        == f"pdf-ingestion:7:{project_id}:request-1"
    )
    library = classify_document_access(
        has_library_entry=True,
        accessible_project_id=None,
        project_was_requested=False,
    )
    assert library is not None and library.is_in_library
    assert (
        classify_document_access(
            has_library_entry=True,
            accessible_project_id=None,
            project_was_requested=True,
        )
        is None
    )


@pytest.mark.parametrize(
    ("state", "can_begin", "can_complete", "can_fail"),
    [
        (DocumentProcessingStatus.PENDING, True, True, True),
        (DocumentProcessingStatus.PROCESSING, False, True, True),
        (DocumentProcessingStatus.COMPLETED, False, True, False),
        (DocumentProcessingStatus.FAILED, True, False, True),
    ],
)
def test_document_processing_state_machine(
    state: DocumentProcessingStatus,
    can_begin: bool,
    can_complete: bool,
    can_fail: bool,
) -> None:
    assert can_begin_processing(state) is can_begin
    assert can_complete_processing(state) is can_complete
    assert can_fail_processing(state) is can_fail


@pytest.mark.parametrize(
    ("state", "complete", "fail", "heartbeat", "terminal"),
    [
        (JobStatus.PENDING, True, True, False, False),
        (JobStatus.RUNNING, True, True, True, False),
        (JobStatus.COMPLETED, False, False, False, True),
        (JobStatus.FAILED, False, False, False, True),
        (JobStatus.CANCELLED, False, False, False, True),
    ],
)
def test_job_terminal_states_are_irreversible(
    state: JobStatus,
    complete: bool,
    fail: bool,
    heartbeat: bool,
    terminal: bool,
) -> None:
    assert can_complete_job(state) is complete
    assert can_fail_job(state) is fail
    assert can_heartbeat_job(state) is heartbeat
    assert is_terminal_job(state) is terminal


def test_job_claim_allows_pending_or_expired_running_jobs() -> None:
    now = datetime.now(UTC)
    assert can_claim_job(JobStatus.PENDING, lease_expires_at=None, now=now)
    assert can_claim_job(
        JobStatus.RUNNING,
        lease_expires_at=now - timedelta(seconds=1),
        now=now,
    )
    assert not can_claim_job(
        JobStatus.RUNNING,
        lease_expires_at=now + timedelta(seconds=1),
        now=now,
    )


def test_zotero_import_policy_canonicalizes_and_replays_completed_results() -> None:
    payload = canonical_import_payload(["B", "A"])
    assert payload == {"item_keys": ["A", "B"]}
    action = decide_import_reservation(
        ImportReservationFacts(
            created=False,
            payload_matches=True,
            status=JobStatus.COMPLETED,
            result={"imported_count": 2},
        )
    )
    assert action is ImportReservationAction.REPLAY


def test_zotero_import_policy_rejects_reused_key_with_different_payload() -> None:
    with pytest.raises(AppError) as error:
        decide_import_reservation(
            ImportReservationFacts(
                created=False,
                payload_matches=False,
                status=JobStatus.PENDING,
                result=None,
            )
        )
    assert error.value.code == "idempotency_key_reused"


def test_identity_domain_separates_product_access_from_sanchezcloud_identity() -> None:
    suspended = AccountAccessFacts("active", is_blocked=True, is_admin=False)
    with pytest.raises(AppError) as suspended_error:
        require_product_access(suspended)
    assert suspended_error.value.code == "identity_suspended"

    with pytest.raises(AppError) as admin_error:
        require_administrator(
            AccountAccessFacts("active", is_blocked=False, is_admin=False)
        )
    assert admin_error.value.code == "admin_required"


@pytest.mark.parametrize(
    ("facts", "permission", "allowed"),
    [
        (
            ProjectAccessFacts(1, 1, ProjectPermissions()),
            ProjectPermission.OWNER,
            True,
        ),
        (
            ProjectAccessFacts(
                2,
                1,
                ProjectPermissions(manage_papers=True),
            ),
            ProjectPermission.MANAGE_PAPERS,
            True,
        ),
        (
            ProjectAccessFacts(2, 1, ProjectPermissions()),
            ProjectPermission.EDIT_PROJECT,
            False,
        ),
    ],
)
def test_project_permission_decisions(
    facts: ProjectAccessFacts,
    permission: ProjectPermission,
    allowed: bool,
) -> None:
    if allowed:
        require_permission(facts, permission)
        return
    with pytest.raises(AppError) as error:
        require_permission(facts, permission)
    assert error.value.kind is FailureKind.PERMISSION_DENIED


def test_project_collaborator_cannot_grant_a_permission_they_do_not_have() -> None:
    access = ProjectAccessFacts(
        user_id=2,
        owner_id=1,
        permissions=ProjectPermissions(manage_papers=True),
    )
    with pytest.raises(AppError) as error:
        require_grant_subset(
            access,
            ProjectPermissions(manage_collaborators=True),
        )
    assert error.value.code == "project_permission_escalation"


@pytest.mark.parametrize(
    ("facts", "can_view", "can_manage", "can_resolve"),
    [
        (
            ResearchAccessFacts(
                ResearchAudienceType.PERSONAL,
                is_creator=True,
                has_audience_access=True,
            ),
            True,
            True,
            False,
        ),
        (
            ResearchAccessFacts(
                ResearchAudienceType.DOCUMENT,
                is_creator=False,
                has_audience_access=True,
            ),
            True,
            False,
            False,
        ),
        (
            ResearchAccessFacts(
                ResearchAudienceType.PROJECT,
                is_creator=True,
                has_audience_access=False,
            ),
            False,
            False,
            False,
        ),
        (
            ResearchAccessFacts(
                ResearchAudienceType.PROJECT,
                is_creator=False,
                has_audience_access=True,
                can_edit_project=True,
            ),
            True,
            False,
            True,
        ),
    ],
)
def test_research_visibility_decisions(
    facts: ResearchAccessFacts,
    can_view: bool,
    can_manage: bool,
    can_resolve: bool,
) -> None:
    decision = evaluate_research_access(facts)
    assert decision.can_view is can_view
    assert decision.can_manage is can_manage
    assert decision.can_resolve is can_resolve


def test_research_creator_becomes_read_only_after_scope_access_is_lost() -> None:
    facts = ResearchAccessFacts(
        ResearchAudienceType.PROJECT,
        is_creator=True,
        has_audience_access=False,
    )
    decision = evaluate_research_access(facts)
    with pytest.raises(AppError) as error:
        require_research_manager(decision)
    assert error.value.code == "research_item_not_found"


@pytest.mark.parametrize(
    ("facts", "can_continue", "reason"),
    [
        (
            ConversationAccessFacts(
                ConversationScopeType.GLOBAL,
                False,
                False,
                None,
                None,
            ),
            True,
            None,
        ),
        (
            ConversationAccessFacts(
                ConversationScopeType.PROJECT,
                True,
                True,
                "Current",
                "Snapshot",
            ),
            False,
            "project_deleted",
        ),
        (
            ConversationAccessFacts(
                ConversationScopeType.PAPER,
                False,
                False,
                None,
                "Paper",
            ),
            False,
            "scope_access_lost",
        ),
    ],
)
def test_conversation_scope_decisions(
    facts: ConversationAccessFacts,
    can_continue: bool,
    reason: str | None,
) -> None:
    decision = evaluate_conversation_access(facts)
    assert decision.can_continue is can_continue
    assert decision.read_only_reason == reason
