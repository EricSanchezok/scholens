"""Pure audience and management rules for Research items."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchAudienceType


@dataclass(frozen=True, slots=True)
class ResearchAccessFacts:
    audience_type: ResearchAudienceType
    is_creator: bool
    has_audience_access: bool
    can_edit_project: bool = False


@dataclass(frozen=True, slots=True)
class ResearchAccessDecision:
    can_view: bool
    can_manage: bool
    can_resolve: bool
    has_audience_access: bool


def evaluate_research_access(facts: ResearchAccessFacts) -> ResearchAccessDecision:
    if facts.audience_type is ResearchAudienceType.PERSONAL:
        return ResearchAccessDecision(
            can_view=facts.is_creator and facts.has_audience_access,
            can_manage=facts.is_creator and facts.has_audience_access,
            can_resolve=False,
            has_audience_access=facts.has_audience_access,
        )
    return ResearchAccessDecision(
        can_view=facts.has_audience_access,
        can_manage=facts.is_creator and facts.has_audience_access,
        can_resolve=facts.has_audience_access
        and (facts.is_creator or facts.can_edit_project),
        has_audience_access=facts.has_audience_access,
    )


def require_research_visible(decision: ResearchAccessDecision) -> None:
    if not decision.can_view:
        raise AppError(
            code="research_item_not_found",
            message="Research item not found",
            kind=FailureKind.NOT_FOUND,
        )


def require_research_manager(decision: ResearchAccessDecision) -> None:
    require_research_visible(decision)
    if not decision.can_manage:
        raise AppError(
            code="research_item_permission_denied",
            message="Only the creator can modify this research item",
            kind=FailureKind.PERMISSION_DENIED,
        )


__all__ = [
    "ResearchAccessDecision",
    "ResearchAccessFacts",
    "evaluate_research_access",
    "require_research_manager",
    "require_research_visible",
]
