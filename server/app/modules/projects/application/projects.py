"""Project collaboration use cases shared by inbound transports."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationChange,
    ResourceRef,
)
from app.modules.papers.application.contracts.documents import (
    LibraryOutputResponse,
    LibraryOutputSort,
)
from app.modules.papers.application.downloads import PaperDownloadSigner
from app.modules.projects.application.actions import (
    PROJECT_COLLABORATOR_LEFT,
    PROJECT_COLLABORATOR_REMOVED,
    PROJECT_COLLABORATOR_UPDATED,
    PROJECT_CREATED,
    PROJECT_DELETED,
    PROJECT_INVITATION_ACCEPTED,
    PROJECT_INVITATION_CREATED,
    PROJECT_INVITATION_RESENT,
    PROJECT_INVITATION_REVOKED,
    PROJECT_OWNERSHIP_TRANSFERRED,
    PROJECT_PAPER_COLLECTED,
    PROJECT_PAPER_REMOVED,
    PROJECT_PAPERS_ADDED,
    PROJECT_UPDATED,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
    ProjectListResponse,
    ProjectOutputListResponse,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPapersAddedResponse,
    ProjectPaperSort,
    ProjectPaperSummaryResponse,
    ProjectPendingUploadsResponse,
    ProjectResponse,
    ProjectSort,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.projects.application.lifecycle import (
    ProjectDeletionPlan,
    ProjectInvitationCreationPlan,
    ProjectOwnershipTransferPlan,
    ProjectPaperRemovalPlan,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.application.operation_context import OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import PaperStatus, ResearchItemKind


class ProjectPageDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True, slots=True)
class ProjectPagePosition:
    key: str
    id: UUID


@dataclass(frozen=True, slots=True)
class ProjectMemberPagePosition:
    kind: str
    key: str
    user_id: int


@dataclass(frozen=True, slots=True)
class ProjectInvitationPagePosition:
    created_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class ProjectPage:
    items: list[ProjectResponse]
    positions: list[ProjectPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectResourcePreview:
    """One authorization-aware Project row with bounded text fields."""

    value: ProjectResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectResourceCatalogItem:
    """The only Project fields needed by MCP Resource discovery."""

    id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class ProjectResourcePage:
    """A small scalar Project catalog for MCP Resource manifests."""

    items: list[ProjectResourcePreview]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectResourcePaperPage:
    value: ProjectPaperListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectResourceMemberPage:
    value: ProjectCollaboratorListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectSummaryPage:
    """SQL-bounded Project rows with the positions of the full collection."""

    items: list[ProjectResourcePreview]
    positions: list[ProjectPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectSummaryList:
    value: ProjectListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectPaperSummaryPage:
    """SQL-bounded Project-paper rows with full keyset metadata."""

    items: list[ProjectPaperSummaryResponse]
    positions: list[ProjectPagePosition]
    has_more: bool
    total_count: int
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectPaperSummaryList:
    value: ProjectPaperListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectPaperPage:
    items: list[ProjectPaperSummaryResponse]
    positions: list[ProjectPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectOutputPage:
    items: list[LibraryOutputResponse]
    positions: list[ProjectPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectMemberPage:
    items: list[ProjectCollaboratorResponse]
    positions: list[ProjectMemberPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class ProjectInvitationPage:
    items: list[ProjectInvitationResponse]
    positions: list[ProjectInvitationPagePosition]
    has_more: bool


@dataclass(frozen=True, slots=True)
class ProjectUpdateResult:
    response: ProjectResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class ProjectCollaboratorUpdateResult:
    response: ProjectCollaboratorResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class AcceptedProjectInvitation:
    project_id: UUID
    invitation_id: UUID


@dataclass(frozen=True, slots=True)
class ProjectDocumentCollection:
    document_id: UUID
    added_to_library: bool


@dataclass(frozen=True, slots=True)
class ProjectDeletion:
    created_cleanup_job_count: int
    created_cleanup_job_ids: Iterator[UUID]


@dataclass(frozen=True, slots=True)
class ProjectPaperRemoval:
    created_gc_job_id: UUID | None


class ProjectGateway(Protocol):
    def create(
        self,
        *,
        owner_id: int,
        request: ProjectCreateRequest,
    ) -> ProjectResponse: ...

    def list_projects(
        self,
        *,
        user_id: int,
        query: str | None,
        sort: ProjectSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPage: ...

    def list_project_summaries(
        self,
        *,
        user_id: int,
        query: str | None,
        sort: ProjectSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectSummaryPage: ...

    def list_resource_projects(
        self,
        *,
        user_id: int,
        limit: int,
        document_id: UUID | None = None,
    ) -> ProjectResourcePage: ...

    def list_resource_catalog(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[ProjectResourceCatalogItem]: ...

    def get_resource_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> ProjectResourcePreview | None: ...

    def list_resource_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourcePaperPage: ...

    def list_resource_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourceMemberPage: ...

    def get(self, *, user_id: int, project_id: UUID) -> ProjectResponse: ...

    def update(
        self,
        *,
        user_id: int,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectUpdateResult: ...

    def plan_delete(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> ProjectDeletionPlan: ...

    def delete(
        self,
        *,
        user_id: int,
        project_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
        plan: ProjectDeletionPlan | None = None,
    ) -> ProjectDeletion: ...

    def list_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ProjectCollaboratorResponse]: ...

    def list_members_page(
        self,
        *,
        user_id: int,
        project_id: UUID,
        limit: int,
        position: ProjectMemberPagePosition | None,
    ) -> ProjectMemberPage: ...

    def get_member(
        self,
        *,
        user_id: int,
        project_id: UUID,
        target_user_id: int,
    ) -> ProjectCollaboratorResponse: ...

    def update_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorUpdateResult: ...

    def remove_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
    ) -> None: ...

    def leave(self, *, user_id: int, project_id: UUID) -> None: ...

    def plan_transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectOwnershipTransferPlan: ...

    def transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
        plan: ProjectOwnershipTransferPlan | None = None,
    ) -> ProjectResponse: ...

    def accept_invitation(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> AcceptedProjectInvitation: ...

    def validate_invitation_token(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> None:
        """Validate the token and current invitation state without mutation."""
        ...

    def list_invitations(
        self,
        *,
        actor_id: int,
        project_id: UUID,
    ) -> list[ProjectInvitationResponse]: ...

    def list_invitations_page(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        limit: int,
        position: ProjectInvitationPagePosition | None,
    ) -> ProjectInvitationPage: ...

    def get_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse | None: ...

    def plan_invitation_creation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> ProjectInvitationCreationPlan: ...

    def create_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
        plan: ProjectInvitationCreationPlan | None = None,
    ) -> ProjectInvitationResponse: ...

    def resend_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse: ...

    def revoke_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> bool: ...

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectDocumentCollection | None: ...

    def add_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> tuple[int, int]: ...

    def list_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
        load_preview_urls: bool,
        query: str | None,
        personal_statuses: tuple[PaperStatus, ...],
        personal_tag_ids: tuple[UUID, ...],
        sort: ProjectPaperSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPaperPage: ...

    def list_document_summaries(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        query: str | None,
        personal_statuses: tuple[PaperStatus, ...],
        personal_tag_ids: tuple[UUID, ...],
        sort: ProjectPaperSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPaperSummaryPage: ...

    def list_outputs(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        sort: LibraryOutputSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
        maximum_payload_json_bytes: int | None = None,
    ) -> ProjectOutputPage: ...

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse: ...

    def document_storage_key(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> str | None: ...

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> list[ProjectResponse]: ...

    def list_projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPage: ...

    def list_project_summaries_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectSummaryPage: ...

    def remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> ProjectPaperRemoval: ...

    def plan_remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectPaperRemovalPlan: ...


class ProjectCapacity(Protocol):
    def require_create(self, *, actor: Actor) -> None: ...


class Projects:
    def __init__(
        self,
        *,
        gateway: ProjectGateway,
        capacity: ProjectCapacity,
        signer: PaperDownloadSigner,
        cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._signer = signer
        self._cursors = cursors
        self._journal = journal

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ProjectCreateRequest,
    ) -> ProjectResponse:
        self._capacity.require_create(actor=actor)
        result = self._gateway.create(owner_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_CREATED,
            resources=(ResourceRef(type="project", id=str(result.id)),),
        )
        return result

    def list(
        self,
        *,
        actor: Actor,
        query: str | None = None,
        sort: ProjectSort = ProjectSort.ACTIVITY_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProjectListResponse:
        normalized_query, filters, direction, position = self._project_list_request(
            actor=actor,
            query=query,
            sort=sort,
            cursor=cursor,
        )
        page = self._gateway.list_projects(
            user_id=actor.id,
            query=normalized_query,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        return ProjectListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )

    def summary_list(
        self,
        *,
        actor: Actor,
        query: str | None = None,
        sort: ProjectSort = ProjectSort.ACTIVITY_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProjectSummaryList:
        """Return a model-facing Project page without hydrating ORM entities."""

        normalized_query, filters, direction, position = self._project_list_request(
            actor=actor,
            query=query,
            sort=sort,
            cursor=cursor,
        )
        page = self._gateway.list_project_summaries(
            user_id=actor.id,
            query=normalized_query,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        value = ProjectListResponse(
            items=[preview.value for preview in page.items],
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )
        return ProjectSummaryList(
            value=value,
            content_truncated=any(item.content_truncated for item in page.items),
        )

    def _project_list_request(
        self,
        *,
        actor: Actor,
        query: str | None,
        sort: ProjectSort,
        cursor: str | None,
    ) -> tuple[
        str | None,
        dict[str, object],
        ProjectPageDirection,
        ProjectPagePosition | None,
    ]:
        normalized_query = query.strip() if query and query.strip() else None
        # keyset pagination positions on (key, id); limit is a page-size
        # preference, not a filter, so it must not bind the cursor.
        filters: dict[str, object] = {
            "q": normalized_query,
            "sort": sort.value,
        }
        direction, position = self._decode_cursor(
            actor=actor,
            collection="projects",
            filters=filters,
            cursor=cursor,
        )
        return normalized_query, filters, direction, position

    def resource_projects(
        self,
        *,
        actor: Actor,
        limit: int,
        document_id: UUID | None = None,
    ) -> ProjectResourcePage:
        """List bounded scalar previews for an MCP Resource manifest."""

        if not 1 <= limit <= 25:
            raise ValueError("Project Resource page limit is outside its safe bound")
        return self._gateway.list_resource_projects(
            user_id=actor.id,
            limit=limit,
            document_id=document_id,
        )

    def resource_catalog(
        self,
        *,
        actor: Actor,
        limit: int,
    ) -> Sequence[ProjectResourceCatalogItem]:
        """List only bounded ids/titles for MCP Resource discovery."""

        if not 1 <= limit <= 25:
            raise ValueError("Project Resource catalog limit is outside its safe bound")
        return self._gateway.list_resource_catalog(
            user_id=actor.id,
            limit=limit,
        )

    def resource_project(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectResourcePreview:
        """Get a bounded scalar Project preview after access filtering."""

        result = self._gateway.get_resource_project(
            user_id=actor.id,
            project_id=project_id,
        )
        if result is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        return result

    def resource_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourcePaperPage:
        if not 1 <= limit <= 10:
            raise ValueError("Project Resource paper limit is outside its safe bound")
        return self._gateway.list_resource_documents(
            actor=actor,
            project_id=project_id,
            limit=limit,
        )

    def resource_members(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourceMemberPage:
        if not 1 <= limit <= 50:
            raise ValueError("Project Resource member limit is outside its safe bound")
        return self._gateway.list_resource_members(
            user_id=actor.id,
            project_id=project_id,
            limit=limit,
        )

    def get(self, *, actor: Actor, project_id: UUID) -> ProjectResponse:
        return self._gateway.get(user_id=actor.id, project_id=project_id)

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectResponse:
        result = self._gateway.update(
            user_id=actor.id,
            project_id=project_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_UPDATED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            )
        return result.response

    def delete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        plan: ProjectDeletionPlan | None = None,
    ) -> None:
        if plan is None:
            plan = self.plan_delete(actor=actor, project_id=project_id)
        result = self._gateway.delete(
            user_id=actor.id,
            project_id=project_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
            plan=plan,
        )

        def deletion_changes() -> Iterator[OperationChange]:
            yield OperationChange(
                action=PROJECT_DELETED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            )
            observed_job_count = 0
            for job_id in result.created_cleanup_job_ids:
                observed_job_count += 1
                yield OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef(type="job", id=str(job_id)),),
                )
            if observed_job_count != result.created_cleanup_job_count:
                raise RuntimeError("project_cleanup_job_audit_count_mismatch")

        self._journal.append_many_batched(
            actor=actor,
            operation=operation,
            changes=deletion_changes(),
        )

    def plan_delete(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectDeletionPlan:
        return self._gateway.plan_delete(
            user_id=actor.id,
            project_id=project_id,
        )

    def members(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectCollaboratorListResponse:
        items = self._gateway.list_members(
            user_id=actor.id,
            project_id=project_id,
        )
        return ProjectCollaboratorListResponse(
            items=items,
            total_count=len(items),
        )

    def members_page(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ProjectCollaboratorListResponse:
        position = self._decode_member_cursor(
            actor=actor,
            project_id=project_id,
            cursor=cursor,
        )
        page = self._gateway.list_members_page(
            user_id=actor.id,
            project_id=project_id,
            limit=limit,
            position=position,
        )
        return ProjectCollaboratorListResponse(
            items=page.items,
            next_cursor=self._member_page_cursor(
                actor=actor,
                project_id=project_id,
                page=page,
            ),
            total_count=page.total_count,
        )

    def member(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        user_id: int,
    ) -> ProjectCollaboratorResponse:
        return self._gateway.get_member(
            user_id=actor.id,
            project_id=project_id,
            target_user_id=user_id,
        )

    def update_member(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorResponse:
        result = self._gateway.update_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_COLLABORATOR_UPDATED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(type="user", id=str(user_id)),
                ),
            )
        return result.response

    def remove_member(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        user_id: int,
    ) -> None:
        self._gateway.remove_member(
            actor_id=actor.id,
            project_id=project_id,
            user_id=user_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_COLLABORATOR_REMOVED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(user_id)),
            ),
        )

    def leave(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
    ) -> None:
        self._gateway.leave(user_id=actor.id, project_id=project_id)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_COLLABORATOR_LEFT,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(actor.id)),
            ),
        )

    def transfer(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectTransferRequest,
        plan: ProjectOwnershipTransferPlan | None = None,
    ) -> ProjectResponse:
        if plan is None:
            plan = self.plan_transfer(
                actor=actor,
                project_id=project_id,
                request=request,
            )
        result = self._gateway.transfer(
            owner_id=actor.id,
            project_id=project_id,
            request=request,
            plan=plan,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_OWNERSHIP_TRANSFERRED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="user", id=str(request.new_owner_id)),
            ),
        )
        return result

    def plan_transfer(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectOwnershipTransferPlan:
        return self._gateway.plan_transfer(
            owner_id=actor.id,
            project_id=project_id,
            request=request,
        )

    def accept_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        raw_token: str,
    ) -> UUID:
        accepted = self._gateway.accept_invitation(
            raw_token=raw_token,
            user_id=actor.id,
            email=actor.email,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_ACCEPTED,
            resources=(
                ResourceRef(type="project", id=str(accepted.project_id)),
                ResourceRef(
                    type="project_invitation",
                    id=str(accepted.invitation_id),
                ),
            ),
        )
        return accepted.project_id

    def validate_invitation_token(self, *, actor: Actor, raw_token: str) -> None:
        """Validate every acceptance precondition before showing a preview."""
        self._gateway.validate_invitation_token(
            raw_token=raw_token,
            user_id=actor.id,
            email=actor.email,
        )

    def invitations(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectInvitationListResponse:
        return ProjectInvitationListResponse(
            items=self._gateway.list_invitations(
                actor_id=actor.id,
                project_id=project_id,
            )
        )

    def invitations_page(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProjectInvitationListResponse:
        position = self._decode_invitation_cursor(
            actor=actor,
            project_id=project_id,
            cursor=cursor,
        )
        page = self._gateway.list_invitations_page(
            actor_id=actor.id,
            project_id=project_id,
            limit=limit,
            position=position,
        )
        return ProjectInvitationListResponse(
            items=page.items,
            next_cursor=self._invitation_page_cursor(
                actor=actor,
                project_id=project_id,
                page=page,
            ),
        )

    def invitation(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse | None:
        return self._gateway.get_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )

    def create_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
        plan: ProjectInvitationCreationPlan | None = None,
    ) -> ProjectInvitationResponse:
        if plan is None:
            plan = self.plan_invitation_creation(
                actor=actor,
                project_id=project_id,
                request=request,
            )
        invitation = self._gateway.create_invitation(
            actor_id=actor.id,
            project_id=project_id,
            request=request,
            plan=plan,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_CREATED,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(
                    type="project_invitation",
                    id=str(invitation.id),
                ),
            ),
        )
        return invitation

    def plan_invitation_creation(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> ProjectInvitationCreationPlan:
        return self._gateway.plan_invitation_creation(
            actor_id=actor.id,
            project_id=project_id,
            request=request,
        )

    def resend_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse:
        invitation = self._gateway.resend_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PROJECT_INVITATION_RESENT,
            resources=(
                ResourceRef(type="project", id=str(project_id)),
                ResourceRef(type="project_invitation", id=str(invitation_id)),
            ),
        )
        return invitation

    def revoke_invitation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None:
        changed = self._gateway.revoke_invitation(
            actor_id=actor.id,
            project_id=project_id,
            invitation_id=invitation_id,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_INVITATION_REVOKED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(
                        type="project_invitation",
                        id=str(invitation_id),
                    ),
                ),
            )

    def collect_document(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectPaperCollectedResponse:
        result = self._gateway.collect_document(actor=actor, request=request)
        if result is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        if result.added_to_library:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_PAPER_COLLECTED,
                resources=(
                    ResourceRef(
                        type="project",
                        id=str(request.source_project_id),
                    ),
                    ResourceRef(type="document", id=str(result.document_id)),
                ),
            )
        return ProjectPaperCollectedResponse(document_id=result.document_id)

    def add_documents(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> ProjectPapersAddedResponse:
        added_count, existing_count = self._gateway.add_documents(
            actor=actor,
            project_id=project_id,
            request=request,
        )
        if added_count:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PROJECT_PAPERS_ADDED,
                resources=(ResourceRef(type="project", id=str(project_id)),),
            )
        return ProjectPapersAddedResponse(
            added_count=added_count,
            existing_count=existing_count,
        )

    def documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
        load_preview_urls: bool = False,
        query: str | None = None,
        personal_statuses: tuple[PaperStatus, ...] = (),
        personal_tag_ids: tuple[UUID, ...] = (),
        sort: ProjectPaperSort = ProjectPaperSort.ADDED_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProjectPaperListResponse:
        (
            normalized_query,
            normalized_statuses,
            normalized_tag_ids,
            filters,
            direction,
            position,
        ) = self._project_document_request(
            actor=actor,
            project_id=project_id,
            query=query,
            personal_statuses=personal_statuses,
            personal_tag_ids=personal_tag_ids,
            sort=sort,
            load_urls=load_urls,
            load_preview_urls=load_preview_urls,
            cursor=cursor,
        )
        page = self._gateway.list_documents(
            actor=actor,
            project_id=project_id,
            load_urls=load_urls,
            load_preview_urls=load_preview_urls,
            query=normalized_query,
            personal_statuses=normalized_statuses,
            personal_tag_ids=normalized_tag_ids,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        return ProjectPaperListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="project-papers",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="project-papers",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )

    def document_summaries(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        query: str | None = None,
        personal_statuses: tuple[PaperStatus, ...] = (),
        personal_tag_ids: tuple[UUID, ...] = (),
        sort: ProjectPaperSort = ProjectPaperSort.ADDED_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ProjectPaperSummaryList:
        """Return a bounded Project-paper page with the historical cursor binding."""

        (
            normalized_query,
            normalized_statuses,
            normalized_tag_ids,
            filters,
            direction,
            position,
        ) = self._project_document_request(
            actor=actor,
            project_id=project_id,
            query=query,
            personal_statuses=personal_statuses,
            personal_tag_ids=personal_tag_ids,
            sort=sort,
            load_urls=False,
            load_preview_urls=False,
            cursor=cursor,
        )
        page = self._gateway.list_document_summaries(
            actor=actor,
            project_id=project_id,
            query=normalized_query,
            personal_statuses=normalized_statuses,
            personal_tag_ids=normalized_tag_ids,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        value = ProjectPaperListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="project-papers",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="project-papers",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )
        return ProjectPaperSummaryList(
            value=value,
            content_truncated=page.content_truncated,
        )

    def _project_document_request(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        query: str | None,
        personal_statuses: tuple[PaperStatus, ...],
        personal_tag_ids: tuple[UUID, ...],
        sort: ProjectPaperSort,
        load_urls: bool,
        load_preview_urls: bool,
        cursor: str | None,
    ) -> tuple[
        str | None,
        tuple[PaperStatus, ...],
        tuple[UUID, ...],
        dict[str, object],
        ProjectPageDirection,
        ProjectPagePosition | None,
    ]:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_statuses = tuple(
            sorted(set(personal_statuses), key=lambda value: value.value)
        )
        normalized_tag_ids = tuple(sorted(set(personal_tag_ids), key=str))
        filters: dict[str, object] = {
            "project_id": str(project_id),
            "q": normalized_query,
            "sort": sort.value,
            "load_urls": load_urls,
            "load_preview_urls": load_preview_urls,
            "personal_statuses": [value.value for value in normalized_statuses],
            "personal_tag_ids": [str(value) for value in normalized_tag_ids],
        }
        direction, position = self._decode_cursor(
            actor=actor,
            collection="project-papers",
            filters=filters,
            cursor=cursor,
        )
        return (
            normalized_query,
            normalized_statuses,
            normalized_tag_ids,
            filters,
            direction,
            position,
        )

    def outputs(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        query: str | None = None,
        kinds: tuple[ResearchItemKind, ...] = (),
        sort: LibraryOutputSort = LibraryOutputSort.UPDATED_DESC,
        cursor: str | None = None,
        limit: int = 20,
        maximum_payload_json_bytes: int | None = None,
    ) -> ProjectOutputListResponse:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_kinds = tuple(sorted(set(kinds), key=lambda value: value.value))
        filters = {
            "project_id": str(project_id),
            "q": normalized_query,
            "kinds": [kind.value for kind in normalized_kinds],
            "sort": sort.value,
        }
        direction, position = self._decode_cursor(
            actor=actor,
            collection="project-outputs",
            filters=filters,
            cursor=cursor,
        )
        page = self._gateway.list_outputs(
            actor=actor,
            project_id=project_id,
            query=normalized_query,
            kinds=normalized_kinds,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
            maximum_payload_json_bytes=maximum_payload_json_bytes,
        )
        return ProjectOutputListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="project-outputs",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="project-outputs",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )

    def _decode_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        cursor: str | None,
    ) -> tuple[ProjectPageDirection, ProjectPagePosition | None]:
        if cursor is None:
            return ProjectPageDirection.FORWARD, None
        try:
            direction, key, item_id = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(actor, collection, filters),
                arity=3,
            )
            return ProjectPageDirection(direction), ProjectPagePosition(
                key=key,
                id=UUID(item_id),
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="project_cursor_invalid",
                message="The Project cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _decode_member_cursor(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        cursor: str | None,
    ) -> ProjectMemberPagePosition | None:
        if cursor is None:
            return None
        filters = {"project_id": str(project_id)}
        try:
            kind, key, user_id_text = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(
                    actor,
                    "project-members",
                    filters,
                ),
                arity=3,
            )
            if kind not in {"owner", "collaborator"}:
                raise ValueError("unsupported Project member cursor kind")
            user_id = int(user_id_text)
            if user_id <= 0:
                raise ValueError("invalid Project member cursor user ID")
            if kind == "owner" and key:
                raise ValueError("invalid Project owner cursor key")
            if kind == "collaborator":
                datetime.fromisoformat(key)
            return ProjectMemberPagePosition(
                kind=kind,
                key=key,
                user_id=user_id,
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="project_cursor_invalid",
                message="The Project cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _decode_invitation_cursor(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        cursor: str | None,
    ) -> ProjectInvitationPagePosition | None:
        if cursor is None:
            return None
        filters = {"project_id": str(project_id), "state": "active"}
        try:
            created_at_text, invitation_id_text = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(
                    actor,
                    "project-invitations",
                    filters,
                ),
                arity=2,
            )
            created_at = datetime.fromisoformat(created_at_text)
            if created_at.tzinfo is None:
                raise ValueError(
                    "Project invitation cursor timestamp requires timezone"
                )
            return ProjectInvitationPagePosition(
                created_at=created_at,
                id=UUID(invitation_id_text),
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="project_cursor_invalid",
                message="The Project cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _member_page_cursor(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        page: ProjectMemberPage,
    ) -> str | None:
        if not page.has_more or not page.positions:
            return None
        position = page.positions[-1]
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(
                actor,
                "project-members",
                {"project_id": str(project_id)},
            ),
            values=(position.kind, position.key, str(position.user_id)),
        )

    def _invitation_page_cursor(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        page: ProjectInvitationPage,
    ) -> str | None:
        if not page.has_more or not page.positions:
            return None
        position = page.positions[-1]
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(
                actor,
                "project-invitations",
                {"project_id": str(project_id), "state": "active"},
            ),
            values=(position.created_at.isoformat(), str(position.id)),
        )

    def _page_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        page: (
            ProjectPage
            | ProjectPaperPage
            | ProjectOutputPage
            | ProjectSummaryPage
            | ProjectPaperSummaryPage
        ),
        direction: ProjectPageDirection,
        had_position: bool,
        previous: bool,
    ) -> str | None:
        if not page.positions:
            return None
        available = (
            page.has_more
            if (previous and direction is ProjectPageDirection.BACKWARD)
            or (not previous and direction is ProjectPageDirection.FORWARD)
            else had_position
        )
        if not available:
            return None
        target_direction = (
            ProjectPageDirection.BACKWARD if previous else ProjectPageDirection.FORWARD
        )
        position = page.positions[0] if previous else page.positions[-1]
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(actor, collection, filters),
            values=(target_direction.value, position.key, str(position.id)),
        )

    @staticmethod
    def _cursor_binding(
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
    ) -> str:
        return json.dumps(
            {
                "revision": "projects-v1",
                "user_id": actor.id,
                "collection": collection,
                "filters": filters,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse:
        return self._gateway.pending_uploads(actor=actor, project_id=project_id)

    def document_download(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectPaperFileUrlResponse:
        storage_key = self._gateway.document_storage_key(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
        )
        if storage_key is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        try:
            return ProjectPaperFileUrlResponse(
                file_url=self._signer.sign(storage_key=storage_key)
            )
        except RuntimeError as exc:
            raise AppError(
                code="document_file_url_unavailable",
                message="The document file is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> ProjectListResponse:
        items = self._gateway.projects_for_document(
            actor=actor,
            document_id=document_id,
        )
        return ProjectListResponse(
            items=items,
            total_count=len(items),
        )

    def projects_for_document_page(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
    ) -> ProjectListResponse:
        filters = {"document_id": str(document_id)}
        direction, position = self._decode_cursor(
            actor=actor,
            collection="paper-projects",
            filters=filters,
            cursor=cursor,
        )
        page = self._gateway.list_projects_for_document(
            actor=actor,
            document_id=document_id,
            limit=limit,
            direction=direction,
            position=position,
        )
        return ProjectListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="paper-projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="paper-projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )

    def project_summaries_for_document_page(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        cursor: str | None = None,
        limit: int = 25,
    ) -> ProjectSummaryList:
        """Return bounded Project previews for one authorized document."""

        filters = {"document_id": str(document_id)}
        direction, position = self._decode_cursor(
            actor=actor,
            collection="paper-projects",
            filters=filters,
            cursor=cursor,
        )
        page = self._gateway.list_project_summaries_for_document(
            actor=actor,
            document_id=document_id,
            limit=limit,
            direction=direction,
            position=position,
        )
        value = ProjectListResponse(
            items=[preview.value for preview in page.items],
            previous_cursor=self._page_cursor(
                actor=actor,
                collection="paper-projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                collection="paper-projects",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )
        return ProjectSummaryList(
            value=value,
            content_truncated=any(item.content_truncated for item in page.items),
        )

    def remove_document(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
        document_id: UUID,
    ) -> None:
        result = self._gateway.remove_document(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes = [
            OperationChange(
                action=PROJECT_PAPER_REMOVED,
                resources=(
                    ResourceRef(type="project", id=str(project_id)),
                    ResourceRef(type="document", id=str(document_id)),
                ),
            )
        ]
        if result.created_gc_job_id is not None:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(
                        ResourceRef(type="job", id=str(result.created_gc_job_id)),
                    ),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )

    def plan_remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectPaperRemovalPlan:
        return self._gateway.plan_remove_document(
            actor=actor,
            project_id=project_id,
            document_id=document_id,
        )
