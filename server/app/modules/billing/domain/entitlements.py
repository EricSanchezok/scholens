"""Pure subscription entitlement and quota decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import SubscriptionPlan, SubscriptionStatus

PAPER_UPLOAD_KEY = "paper_uploads"
KB_SIZE_KEY = "knowledge_base_size_kb"
TOKEN_CREDITS_KEY = "token_credits_weekly"
PROJECTS_KEY = "projects"
PROJECT_PAPERS_KEY = "project_papers"


@dataclass(frozen=True, slots=True)
class PlanEntitlements:
    paper_uploads: int
    knowledge_base_size_kb: int
    token_credits_weekly: int
    projects: int
    project_papers: int
    zotero_auto_sync: bool

    def as_limits(self) -> dict[str, int]:
        return {
            PAPER_UPLOAD_KEY: self.paper_uploads,
            KB_SIZE_KEY: self.knowledge_base_size_kb,
            TOKEN_CREDITS_KEY: self.token_credits_weekly,
            PROJECTS_KEY: self.projects,
            PROJECT_PAPERS_KEY: self.project_papers,
        }


PLAN_ENTITLEMENTS = {
    SubscriptionPlan.BASIC: PlanEntitlements(
        paper_uploads=300,
        knowledge_base_size_kb=5 * 1024 * 1024,
        token_credits_weekly=30_000_000,
        projects=10,
        project_papers=300,
        zotero_auto_sync=False,
    ),
    SubscriptionPlan.RESEARCHER: PlanEntitlements(
        paper_uploads=5_000,
        knowledge_base_size_kb=100 * 1024 * 1024,
        token_credits_weekly=300_000_000,
        projects=100,
        project_papers=5_000,
        zotero_auto_sync=True,
    ),
}

PLAN_LABELS = {
    SubscriptionPlan.BASIC: "Basic",
    SubscriptionPlan.RESEARCHER: "Researcher",
}


@dataclass(frozen=True, slots=True)
class SubscriptionFacts:
    plan: SubscriptionPlan
    status: SubscriptionStatus
    current_period_end: datetime | None


@dataclass(frozen=True, slots=True)
class PlanGrantFacts:
    plan: SubscriptionPlan
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EntitlementResolution:
    plan: SubscriptionPlan
    source: str
    limits: PlanEntitlements
    overrides: Mapping[str, int]
    grant_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AccountCapacityFacts:
    current_documents: int
    current_storage_kb: int
    added_documents: int
    added_storage_kb: int
    project_owner: bool = False


def effective_plan(
    subscription: SubscriptionFacts | None,
    *,
    now: datetime,
    grant: PlanGrantFacts | None = None,
) -> SubscriptionPlan:
    subscription_active = (
        subscription is not None
        and subscription.current_period_end is not None
        and subscription.current_period_end > now
        and subscription.status
        in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}
    )
    grant_active = (
        grant is not None and grant.revoked_at is None and grant.expires_at > now
    )
    paid_researcher = bool(
        subscription_active
        and subscription is not None
        and subscription.plan is SubscriptionPlan.RESEARCHER
    )
    granted_researcher = bool(
        grant_active and grant is not None and grant.plan is SubscriptionPlan.RESEARCHER
    )
    if paid_researcher or granted_researcher:
        return SubscriptionPlan.RESEARCHER
    return SubscriptionPlan.BASIC


def entitlements_for(plan: SubscriptionPlan) -> PlanEntitlements:
    return PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS[SubscriptionPlan.BASIC])


def resolve_entitlements(
    subscription: SubscriptionFacts | None,
    *,
    now: datetime,
    grant: PlanGrantFacts | None = None,
    overrides: Mapping[str, int] | None = None,
) -> EntitlementResolution:
    plan = effective_plan(subscription, now=now, grant=grant)
    grant_active = (
        grant is not None
        and grant.revoked_at is None
        and grant.expires_at > now
        and grant.plan is plan
    )
    subscription_active = (
        subscription is not None
        and subscription.current_period_end is not None
        and subscription.current_period_end > now
        and subscription.status
        in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}
        and subscription.plan is plan
    )
    source = (
        "subscription" if subscription_active else "grant" if grant_active else "basic"
    )
    active_overrides = dict(overrides or {})
    limits = entitlements_for(plan)
    if active_overrides:
        unknown = set(active_overrides).difference(limits.as_limits())
        if unknown:
            raise ValueError(f"unsupported entitlement override: {sorted(unknown)[0]}")
        if any(value < 0 for value in active_overrides.values()):
            raise ValueError("entitlement overrides must not be negative")
        limits = replace(
            limits,
            **{
                field_name: active_overrides.get(
                    field_name, getattr(limits, field_name)
                )
                for field_name in limits.as_limits()
            },
        )
    return EntitlementResolution(
        plan=plan,
        source=source,
        limits=limits,
        overrides=active_overrides,
        grant_expires_at=grant.expires_at
        if grant_active and grant is not None
        else None,
    )


def remaining(limit: int, used: int) -> int:
    return max(0, limit - used)


def require_account_document_capacity(
    plan: SubscriptionPlan,
    facts: AccountCapacityFacts,
    *,
    limits: PlanEntitlements | None = None,
) -> None:
    limits = limits or entitlements_for(plan)
    if facts.current_documents + facts.added_documents > limits.paper_uploads:
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if facts.project_owner
                else "paper_quota_exceeded"
            ),
            message="The account's paper limit would be exceeded",
            kind=FailureKind.PERMISSION_DENIED,
        )
    if facts.current_storage_kb + facts.added_storage_kb > (
        limits.knowledge_base_size_kb
    ):
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if facts.project_owner
                else "storage_quota_exceeded"
            ),
            message="The account's storage limit would be exceeded",
            kind=FailureKind.PERMISSION_DENIED,
        )


def require_project_paper_capacity(
    plan: SubscriptionPlan,
    *,
    current_documents: int,
    added_documents: int,
    limits: PlanEntitlements | None = None,
) -> None:
    resolved_limits = limits or entitlements_for(plan)
    if current_documents + added_documents > resolved_limits.project_papers:
        raise AppError(
            code="project_paper_quota_exceeded",
            message="The Project's paper limit would be exceeded",
            kind=FailureKind.PERMISSION_DENIED,
        )


def paper_upload_denial(
    plan: SubscriptionPlan,
    *,
    current_documents: int,
    limits: PlanEntitlements | None = None,
) -> str | None:
    limit = (limits or entitlements_for(plan)).paper_uploads
    if current_documents < limit:
        return None
    return (
        f"You have reached your paper upload limit ({limit} papers) for the "
        f"{PLAN_LABELS[plan]} plan. Please upgrade your subscription to upload "
        "more papers, or delete existing papers to free up space."
    )


def project_creation_denial(
    plan: SubscriptionPlan,
    *,
    current_projects: int,
    limits: PlanEntitlements | None = None,
) -> str | None:
    limit = (limits or entitlements_for(plan)).projects
    if current_projects < limit:
        return None
    return (
        f"You have reached your project limit ({limit} projects) for the "
        f"{PLAN_LABELS[plan]} plan. Please upgrade your subscription to create "
        "more projects."
    )
