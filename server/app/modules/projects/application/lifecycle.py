"""Typed, transport-neutral plans for confirmed Project lifecycle actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.projects.application.contracts import ProjectPermissionSet
from pydantic import BaseModel, ConfigDict, Field


class ProjectDeletionState(BaseModel):
    """Bounded live facts that determine the impact of deleting one Project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    owner_id: int
    project_updated_at: datetime
    paper_association_count: int = Field(ge=0)
    research_output_count: int = Field(ge=0)
    annotation_thread_count: int = Field(ge=0)
    annotation_comment_count: int = Field(ge=0)
    annotation_revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    collaborator_count: int = Field(ge=0)
    invitation_count: int = Field(ge=0)
    conversation_count: int = Field(ge=0)
    storage_object_count: int = Field(ge=0)
    active_job_count: int = Field(ge=0)
    affected_resource_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProjectDeletionPlan:
    state: ProjectDeletionState
    project_title: str


class ProjectPaperRemovalState(BaseModel):
    """Bounded live facts that invalidate a paper-removal confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    document_id: UUID
    association_id: UUID
    annotation_thread_count: int = Field(ge=0)
    annotation_comment_count: int = Field(ge=0)
    annotation_revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProjectPaperRemovalPlan:
    state: ProjectPaperRemovalState
    project_title: str


class ProjectQuotaOwnerState(BaseModel):
    """One account's complete post-transfer quota calculation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_id: int
    completed_document_count: int = Field(ge=0)
    completed_size_kb: int = Field(ge=0)
    active_reference_count: int = Field(ge=0)
    active_size_kb: int = Field(ge=0)
    paper_limit: int = Field(ge=0)
    storage_limit_kb: int = Field(ge=0)


class ProjectQuotaTransferState(BaseModel):
    """All quota facts whose change would invalidate an ownership preview."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    old_owner_id: int
    new_owner_id: int
    new_owner_project_count: int = Field(ge=0)
    new_owner_project_limit: int = Field(ge=0)
    project_document_count: int = Field(ge=0)
    pending_project_slot_count: int = Field(ge=0)
    project_paper_limit: int = Field(ge=0)
    active_reservation_count: int = Field(ge=0)
    owners: tuple[ProjectQuotaOwnerState, ...]
    reservation_assignment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectReservationAssignment(BaseModel):
    """Exact final billing fields for one locked active upload reservation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reservation_id: UUID
    job_status: str
    job_project_id: UUID | None
    job_document_id: UUID | None
    content_sha256: str | None
    current_quota_owner_id: int
    current_library_quota_owner_id: int | None
    current_reserved_reference_count: int = Field(ge=0)
    current_reserved_size_kb: int = Field(ge=0)
    current_library_reserved_reference_count: int = Field(ge=0)
    current_library_reserved_size_kb: int = Field(ge=0)
    quota_owner_id: int
    library_quota_owner_id: int | None
    reserved_reference_count: int = Field(ge=0)
    reserved_size_kb: int = Field(ge=0)
    library_reserved_reference_count: int = Field(ge=0)
    library_reserved_size_kb: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class ProjectQuotaTransferPlan:
    state: ProjectQuotaTransferState
    assignments: tuple[ProjectReservationAssignment, ...]


class ProjectOwnershipTransferState(BaseModel):
    """State bound to an ownership-transfer confirmation token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    project_updated_at: datetime
    old_owner_id: int
    target_membership_id: UUID
    new_owner_id: int
    target_membership_updated_at: datetime
    target_permissions: ProjectPermissionSet
    target_email: str = Field(min_length=3, max_length=320)
    quota: ProjectQuotaTransferState


@dataclass(frozen=True, slots=True)
class ProjectOwnershipTransferPlan:
    state: ProjectOwnershipTransferState
    project_title: str
    quota: ProjectQuotaTransferPlan


class PendingProjectInvitationState(BaseModel):
    """An unaccepted and unrevoked invitation, including expired rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invitation_id: UUID
    token_revision: int = Field(ge=1)
    permissions: ProjectPermissionSet
    expires_at: datetime
    updated_at: datetime


class ProjectInvitationCreationState(BaseModel):
    """Stable state used before replacing or creating a pending invitation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    project_updated_at: datetime
    normalized_email: str = Field(min_length=3, max_length=320)
    requested_permissions: ProjectPermissionSet
    replaced_invitation: PendingProjectInvitationState | None


@dataclass(frozen=True, slots=True)
class ProjectInvitationCreationPlan:
    state: ProjectInvitationCreationState
    project_title: str
    replaced_invitation_id: UUID | None


__all__ = [
    "PendingProjectInvitationState",
    "ProjectDeletionPlan",
    "ProjectDeletionState",
    "ProjectInvitationCreationPlan",
    "ProjectInvitationCreationState",
    "ProjectOwnershipTransferPlan",
    "ProjectOwnershipTransferState",
    "ProjectQuotaOwnerState",
    "ProjectQuotaTransferPlan",
    "ProjectQuotaTransferState",
    "ProjectReservationAssignment",
    "ProjectPaperRemovalPlan",
    "ProjectPaperRemovalState",
]
