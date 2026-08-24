"""Cross-module Project persistence adapter."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.bootstrap.adapters.project_lifecycle import (
    apply_project_deletion,
    inspect_project_deletion,
    remove_project_papers_and_schedule_gc,
    schedule_project_storage_cleanup,
)
from app.bootstrap.adapters.storage_cleanup import iter_created_cleanup_job_ids
from app.bootstrap.adapters.upload_reservations import (
    apply_project_quota_transfer,
    prepare_project_quota_transfer,
)
from app.database.models import (
    AuthUser,
    JobOperation,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
)
from app.modules.projects.application.contracts import ProjectPermissionSet
from app.modules.projects.application.lifecycle import (
    PendingProjectInvitationState,
    ProjectDeletionPlan,
    ProjectInvitationCreationPlan,
    ProjectInvitationCreationState,
    ProjectOwnershipTransferPlan,
    ProjectOwnershipTransferState,
)
from app.modules.projects.domain import (
    ProjectPermissions,
    require_grant_subset,
    require_member_can_leave,
    require_member_management_target,
    require_member_permission_scope,
)
from app.modules.projects.infrastructure.access import (
    ProjectAccess,
    collaborator_permissions,
    get_project_access,
    require_project_access,
    require_project_access_for_update,
    require_project_permission,
    require_project_permission_for_update,
)
from app.shared.domain import AppError, FailureKind

INVITATION_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class AcceptedInvitation:
    collaborator: ProjectCollaborator
    invitation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UpdatedProject:
    project: Project
    changed: bool


@dataclass(frozen=True, slots=True)
class UpdatedProjectCollaborator:
    collaborator: ProjectCollaborator
    changed: bool


@dataclass(frozen=True, slots=True)
class ProjectDeletionJobs:
    created_job_count: int
    created_job_ids: Iterator[uuid.UUID]


def _normalized_email(email: str) -> str:
    return email.strip().casefold()


def _permission_set(value: ProjectPermissionSet) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=value.edit_project,
        manage_papers=value.manage_papers,
        manage_collaborators=value.manage_collaborators,
    )


def _invitation_permissions(
    invitation: ProjectInvitation,
) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=invitation.can_edit_project,
        manage_papers=invitation.can_manage_papers,
        manage_collaborators=invitation.can_manage_collaborators,
    )


class ProjectRepository:
    def create(
        self, db: Session, *, owner_id: int, title: str, description: str | None
    ) -> Project:
        project = Project(owner_id=owner_id, title=title, description=description)
        db.add(project)
        db.flush()
        db.refresh(project)
        return project

    def get_access(
        self, db: Session, *, project_id: uuid.UUID, user_id: int
    ) -> ProjectAccess:
        return require_project_access(db, project_id=project_id, user_id=user_id)

    def list_accessible(
        self, db: Session, *, user_id: int, limit: int | None = None
    ) -> list[Project]:
        statement = (
            select(Project)
            .outerjoin(
                ProjectCollaborator,
                ProjectCollaborator.project_id == Project.id,
            )
            .where(
                or_(
                    Project.owner_id == user_id,
                    ProjectCollaborator.user_id == user_id,
                )
            )
            .options(joinedload(Project.owner))
            .order_by(Project.updated_at.desc(), Project.id)
            .distinct()
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(db.scalars(statement).unique().all())

    def update(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
        changes: dict[str, object],
    ) -> UpdatedProject:
        access = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=user_id,
            permission="edit_project",
        )
        changed = any(
            getattr(access.project, field) != value for field, value in changes.items()
        )
        for field, value in changes.items():
            setattr(access.project, field, value)
        db.flush()
        db.refresh(access.project)
        return UpdatedProject(project=access.project, changed=changed)

    def plan_delete(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
    ) -> ProjectDeletionPlan:
        access = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=user_id,
            permission="owner",
        )
        return inspect_project_deletion(db, project=access.project)

    def delete(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
        origin_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
        plan: ProjectDeletionPlan | None = None,
    ) -> ProjectDeletionJobs:
        if plan is None:
            plan = self.plan_delete(
                db,
                project_id=project_id,
                user_id=user_id,
            )
        project = db.get(Project, project_id)
        if project is None or plan.state.owner_id != user_id:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        # Read Project-owned object keys while the locked Project and its
        # Research rows still exist. The producer yields unique sorted keys, so
        # storage batch ordinals and digests are stable across retries.
        storage_cleanup = schedule_project_storage_cleanup(
            db,
            project_id=project_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )
        document_gc = remove_project_papers_and_schedule_gc(
            db,
            project_id=project_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )
        apply_project_deletion(db, project=project, plan=plan)
        db.delete(project)
        db.flush()
        created_job_count = document_gc.created_job_count
        if storage_cleanup is not None:
            created_job_count += storage_cleanup.created_job_count
        return ProjectDeletionJobs(
            created_job_count=created_job_count,
            created_job_ids=iter_created_cleanup_job_ids(
                db,
                origin_operation_id=origin_operation_id,
                operations=(JobOperation.DOCUMENT_GC, JobOperation.STORAGE_DELETE),
            ),
        )

    def list_collaborators(
        self, db: Session, *, project_id: uuid.UUID, user_id: int
    ) -> tuple[Project, list[ProjectCollaborator]]:
        access = require_project_access(db, project_id=project_id, user_id=user_id)
        collaborators = list(
            db.scalars(
                select(ProjectCollaborator)
                .where(ProjectCollaborator.project_id == project_id)
                .options(joinedload(ProjectCollaborator.user))
                .order_by(ProjectCollaborator.joined_at, ProjectCollaborator.id)
            ).all()
        )
        return access.project, collaborators

    def update_collaborator(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        target_user_id: int,
        requested: ProjectPermissionSet,
    ) -> UpdatedProjectCollaborator:
        actor = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        require_member_management_target(
            actor.facts,
            target_user_id=target_user_id,
        )
        target = db.scalar(
            select(ProjectCollaborator)
            .where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == target_user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if target is None:
            raise AppError(
                code="project_collaborator_not_found",
                message="Project collaborator not found",
                kind=FailureKind.NOT_FOUND,
            )

        requested_permissions = _permission_set(requested)
        current_permissions = collaborator_permissions(target)
        require_grant_subset(actor.facts, requested_permissions)
        require_member_permission_scope(
            actor.facts,
            target_permissions=current_permissions,
        )

        changed = (
            target.can_edit_project != requested.edit_project
            or target.can_manage_papers != requested.manage_papers
            or target.can_manage_collaborators != requested.manage_collaborators
        )
        if changed:
            target.can_edit_project = requested.edit_project
            target.can_manage_papers = requested.manage_papers
            target.can_manage_collaborators = requested.manage_collaborators
        db.flush()
        db.refresh(target)
        return UpdatedProjectCollaborator(
            collaborator=target,
            changed=changed,
        )

    def remove_collaborator(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        target_user_id: int,
    ) -> None:
        actor = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        require_member_management_target(
            actor.facts,
            target_user_id=target_user_id,
        )
        target = db.scalar(
            select(ProjectCollaborator)
            .where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == target_user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if target is None:
            raise AppError(
                code="project_collaborator_not_found",
                message="Project collaborator not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_member_permission_scope(
            actor.facts,
            target_permissions=collaborator_permissions(target),
        )
        db.delete(target)
        db.flush()

    def leave(self, db: Session, *, project_id: uuid.UUID, user_id: int) -> None:
        access = require_project_access_for_update(
            db,
            project_id=project_id,
            user_id=user_id,
        )
        require_member_can_leave(
            user_id=user_id,
            owner_id=access.project.owner_id,
        )
        if access.collaborator is None:
            raise RuntimeError("Non-owner project access has no collaborator")
        db.delete(access.collaborator)
        db.flush()

    def plan_transfer(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        owner_id: int,
        new_owner_id: int,
    ) -> ProjectOwnershipTransferPlan:
        access = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=owner_id,
            permission="owner",
        )
        project = access.project
        new_owner_membership = db.scalar(
            select(ProjectCollaborator)
            .where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == new_owner_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if new_owner_membership is None:
            raise AppError(
                code="project_new_owner_not_collaborator",
                message="The new owner must already be a collaborator",
                kind=FailureKind.CONFLICT,
            )
        target_user = db.get(AuthUser, new_owner_id)
        if target_user is None:
            raise RuntimeError("project_transfer_target_user_missing")
        quota = prepare_project_quota_transfer(
            db,
            project=project,
            new_owner_id=new_owner_id,
        )
        return ProjectOwnershipTransferPlan(
            state=ProjectOwnershipTransferState(
                project_id=project.id,
                project_updated_at=project.updated_at,
                old_owner_id=owner_id,
                target_membership_id=new_owner_membership.id,
                new_owner_id=new_owner_id,
                target_membership_updated_at=new_owner_membership.updated_at,
                target_permissions=ProjectPermissionSet(
                    edit_project=new_owner_membership.can_edit_project,
                    manage_papers=new_owner_membership.can_manage_papers,
                    manage_collaborators=(
                        new_owner_membership.can_manage_collaborators
                    ),
                ),
                target_email=target_user.email,
                quota=quota.state,
            ),
            project_title=project.title,
            quota=quota,
        )

    def transfer(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        owner_id: int,
        new_owner_id: int,
        plan: ProjectOwnershipTransferPlan | None = None,
    ) -> Project:
        if plan is None:
            plan = self.plan_transfer(
                db,
                project_id=project_id,
                owner_id=owner_id,
                new_owner_id=new_owner_id,
            )
        project = db.get(Project, project_id)
        new_owner_membership = db.get(
            ProjectCollaborator,
            plan.state.target_membership_id,
        )
        if (
            project is None
            or project.owner_id != owner_id
            or plan.state.project_id != project_id
            or plan.state.new_owner_id != new_owner_id
            or new_owner_membership is None
            or new_owner_membership.project_id != project_id
            or new_owner_membership.user_id != new_owner_id
        ):
            raise RuntimeError("project_ownership_transfer_plan_mismatch")
        apply_project_quota_transfer(
            db,
            project=project,
            new_owner_id=new_owner_id,
            plan=plan.quota,
        )
        db.delete(new_owner_membership)
        db.add(
            ProjectCollaborator(
                project_id=project_id,
                user_id=owner_id,
                can_edit_project=True,
                can_manage_papers=True,
                can_manage_collaborators=True,
            )
        )
        project.owner_id = new_owner_id
        db.flush()
        db.refresh(project)
        return project

    def plan_invitation_creation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        email: str,
        requested: ProjectPermissionSet,
    ) -> ProjectInvitationCreationPlan:
        actor = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        requested_permissions = _permission_set(requested)
        if not actor.permissions.contains(requested_permissions):
            raise AppError(
                code="project_permission_escalation",
                message="You cannot grant a permission you do not have",
                kind=FailureKind.PERMISSION_DENIED,
            )
        project = actor.project

        normalized_email = _normalized_email(email)
        existing_user = db.scalar(
            select(AuthUser).where(AuthUser.email == normalized_email)
        )
        if existing_user is not None:
            if existing_user.id == actor.project.owner_id:
                raise AppError(
                    code="project_collaborator_exists",
                    message="This user already belongs to the Project",
                    kind=FailureKind.CONFLICT,
                )
            existing_member = db.scalar(
                select(ProjectCollaborator).where(
                    ProjectCollaborator.project_id == project_id,
                    ProjectCollaborator.user_id == existing_user.id,
                )
            )
            if existing_member is not None:
                raise AppError(
                    code="project_collaborator_exists",
                    message="This user already belongs to the Project",
                    kind=FailureKind.CONFLICT,
                )

        pending = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.email == normalized_email,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if pending is not None:
            require_grant_subset(actor.facts, _invitation_permissions(pending))
        planned_permissions = ProjectPermissionSet(
            edit_project=requested_permissions.edit_project,
            manage_papers=requested_permissions.manage_papers,
            manage_collaborators=requested_permissions.manage_collaborators,
        )
        return ProjectInvitationCreationPlan(
            state=ProjectInvitationCreationState(
                project_id=project_id,
                project_updated_at=project.updated_at,
                normalized_email=normalized_email,
                requested_permissions=planned_permissions,
                replaced_invitation=(
                    PendingProjectInvitationState(
                        invitation_id=pending.id,
                        token_revision=pending.token_revision,
                        permissions=ProjectPermissionSet(
                            edit_project=pending.can_edit_project,
                            manage_papers=pending.can_manage_papers,
                            manage_collaborators=(pending.can_manage_collaborators),
                        ),
                        expires_at=pending.expires_at,
                        updated_at=pending.updated_at,
                    )
                    if pending is not None
                    else None
                ),
            ),
            project_title=project.title,
            replaced_invitation_id=pending.id if pending is not None else None,
        )

    def create_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        email: str,
        requested: ProjectPermissionSet,
        plan: ProjectInvitationCreationPlan | None = None,
    ) -> ProjectInvitation:
        if plan is None:
            plan = self.plan_invitation_creation(
                db,
                project_id=project_id,
                actor_id=actor_id,
                email=email,
                requested=requested,
            )
        if (
            plan.state.project_id != project_id
            or plan.state.normalized_email != _normalized_email(email)
            or plan.state.requested_permissions
            != ProjectPermissionSet(
                edit_project=requested.edit_project,
                manage_papers=requested.manage_papers,
                manage_collaborators=requested.manage_collaborators,
            )
        ):
            raise RuntimeError("project_invitation_creation_plan_mismatch")

        now = datetime.now(timezone.utc)
        if plan.replaced_invitation_id is not None:
            pending = db.scalar(
                select(ProjectInvitation)
                .where(ProjectInvitation.id == plan.replaced_invitation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            planned_pending = plan.state.replaced_invitation
            if (
                pending is None
                or planned_pending is None
                or pending.project_id != project_id
                or pending.email != plan.state.normalized_email
                or pending.accepted_at is not None
                or pending.revoked_at is not None
                or pending.token_revision != planned_pending.token_revision
                or pending.expires_at != planned_pending.expires_at
                or pending.updated_at != planned_pending.updated_at
                or ProjectPermissionSet(
                    edit_project=pending.can_edit_project,
                    manage_papers=pending.can_manage_papers,
                    manage_collaborators=pending.can_manage_collaborators,
                )
                != planned_pending.permissions
            ):
                raise RuntimeError("project_invitation_replacement_plan_mismatch")
            pending.revoked_at = now
            pending.delivery_lease_id = None
            pending.delivery_lease_expires_at = None
            db.flush()

        invitation = ProjectInvitation(
            project_id=project_id,
            email=plan.state.normalized_email,
            token_revision=1,
            invited_by_id=actor_id,
            can_edit_project=requested.edit_project,
            can_manage_papers=requested.manage_papers,
            can_manage_collaborators=requested.manage_collaborators,
            expires_at=now + INVITATION_TTL,
            delivery_status="pending",
            delivery_attempt_count=0,
            delivery_next_attempt_at=now,
        )
        db.add(invitation)
        db.flush()
        db.refresh(invitation)
        return invitation

    def list_project_invitations(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
    ) -> list[ProjectInvitation]:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        now = datetime.now(timezone.utc)
        return list(
            db.scalars(
                select(ProjectInvitation)
                .where(
                    ProjectInvitation.project_id == project_id,
                    ProjectInvitation.accepted_at.is_(None),
                    ProjectInvitation.revoked_at.is_(None),
                    ProjectInvitation.expires_at > now,
                )
                .options(
                    joinedload(ProjectInvitation.invited_by),
                    joinedload(ProjectInvitation.project),
                )
                .order_by(
                    ProjectInvitation.created_at.desc(),
                    ProjectInvitation.id.desc(),
                )
            ).all()
        )

    def list_project_invitations_page(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        limit: int,
        position_created_at: datetime | None,
        position_id: uuid.UUID | None,
    ) -> list[ProjectInvitation]:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        now = datetime.now(timezone.utc)
        filters = [
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.accepted_at.is_(None),
            ProjectInvitation.revoked_at.is_(None),
            ProjectInvitation.expires_at > now,
        ]
        if position_created_at is not None and position_id is not None:
            filters.append(
                or_(
                    ProjectInvitation.created_at < position_created_at,
                    and_(
                        ProjectInvitation.created_at == position_created_at,
                        ProjectInvitation.id < position_id,
                    ),
                )
            )
        return list(
            db.scalars(
                select(ProjectInvitation)
                .where(*filters)
                .options(
                    joinedload(ProjectInvitation.invited_by),
                    joinedload(ProjectInvitation.project),
                )
                .order_by(
                    ProjectInvitation.created_at.desc(),
                    ProjectInvitation.id.desc(),
                )
                .limit(limit + 1)
            ).all()
        )

    def get_project_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_id: int,
    ) -> ProjectInvitation | None:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        return db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
                ProjectInvitation.expires_at > datetime.now(timezone.utc),
            )
            .options(
                joinedload(ProjectInvitation.invited_by),
                joinedload(ProjectInvitation.project),
            )
        )

    def _require_invitation_acceptance(
        self,
        db: Session,
        *,
        invitation: ProjectInvitation | None,
        user_id: int,
        email: str,
        locked_project: Project | None = None,
        lock_authority: bool = False,
    ) -> tuple[ProjectInvitation, ProjectCollaborator | None]:
        """Validate the complete invitation state without mutating it."""
        now = datetime.now(timezone.utc)
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
        ):
            raise AppError(
                code="project_invitation_invalid",
                message="Invitation is invalid or expired",
                kind=FailureKind.NOT_FOUND,
            )
        if invitation.email != _normalized_email(email):
            raise AppError(
                code="project_invitation_recipient_mismatch",
                message="Sign in with the account that received this invitation",
                kind=FailureKind.PERMISSION_DENIED,
            )
        project = locked_project or db.get(Project, invitation.project_id)
        if project is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        if project.owner_id == user_id:
            raise AppError(
                code="project_collaborator_exists",
                message="This user already belongs to the Project",
                kind=FailureKind.CONFLICT,
            )
        if lock_authority:
            try:
                inviter_access = require_project_access_for_update(
                    db,
                    project_id=invitation.project_id,
                    user_id=invitation.invited_by_id,
                )
            except AppError as exc:
                if exc.code != "project_not_found":
                    raise
                inviter_access = None
        else:
            inviter_access = get_project_access(
                db,
                project_id=invitation.project_id,
                user_id=invitation.invited_by_id,
            )
        requested = _invitation_permissions(invitation)
        if (
            inviter_access is None
            or not inviter_access.can_manage_collaborators
            or not inviter_access.permissions.contains(requested)
        ):
            raise AppError(
                code="project_invitation_authority_revoked",
                message="The inviter no longer has permission to grant this access",
                kind=FailureKind.CONFLICT,
            )

        existing_statement = select(ProjectCollaborator).where(
            ProjectCollaborator.project_id == invitation.project_id,
            ProjectCollaborator.user_id == user_id,
        )
        if lock_authority:
            existing_statement = existing_statement.with_for_update().execution_options(
                populate_existing=True
            )
        existing = db.scalar(existing_statement)
        return invitation, existing

    def _accept_invitation(
        self,
        db: Session,
        *,
        invitation: ProjectInvitation | None,
        user_id: int,
        email: str,
        locked_project: Project | None = None,
        lock_authority: bool = False,
    ) -> ProjectCollaborator:
        invitation, existing = self._require_invitation_acceptance(
            db,
            invitation=invitation,
            user_id=user_id,
            email=email,
            locked_project=locked_project,
            lock_authority=lock_authority,
        )
        now = datetime.now(timezone.utc)
        if existing is not None:
            invitation.accepted_at = now
            invitation.delivery_lease_id = None
            invitation.delivery_lease_expires_at = None
            db.flush()
            return existing

        collaborator = ProjectCollaborator(
            project_id=invitation.project_id,
            user_id=user_id,
            can_edit_project=invitation.can_edit_project,
            can_manage_papers=invitation.can_manage_papers,
            can_manage_collaborators=invitation.can_manage_collaborators,
        )
        invitation.accepted_at = now
        invitation.delivery_lease_id = None
        invitation.delivery_lease_expires_at = None
        db.add(collaborator)
        db.flush()
        db.refresh(collaborator)
        return collaborator

    def validate_invitation(
        self,
        db: Session,
        *,
        invitation_id: uuid.UUID,
        token_revision: int,
        user_id: int,
        email: str,
    ) -> None:
        invitation = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.token_revision == token_revision,
            )
        )
        self._require_invitation_acceptance(
            db,
            invitation=invitation,
            user_id=user_id,
            email=email,
        )

    def accept_invitation(
        self,
        db: Session,
        *,
        invitation_id: uuid.UUID,
        token_revision: int,
        user_id: int,
        email: str,
    ) -> AcceptedInvitation:
        project_id = db.scalar(
            select(ProjectInvitation.project_id).where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.token_revision == token_revision,
            )
        )
        locked_project = (
            db.scalar(
                select(Project)
                .where(Project.id == project_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if project_id is not None
            else None
        )
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.token_revision == token_revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        collaborator = self._accept_invitation(
            db,
            invitation=invitation,
            user_id=user_id,
            email=email,
            locked_project=locked_project,
            lock_authority=True,
        )
        if invitation is None:
            raise RuntimeError("accepted_project_invitation_missing")
        return AcceptedInvitation(
            collaborator=collaborator,
            invitation_id=invitation.id,
        )

    def revoke_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_id: int,
    ) -> bool:
        actor = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_grant_subset(actor.facts, _invitation_permissions(invitation))
        if invitation.accepted_at is not None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        if invitation.revoked_at is not None:
            return False
        invitation.revoked_at = datetime.now(timezone.utc)
        invitation.delivery_lease_id = None
        invitation.delivery_lease_expires_at = None
        db.flush()
        return True

    def resend_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_id: int,
    ) -> ProjectInvitation:
        actor = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
                ProjectInvitation.expires_at > datetime.now(timezone.utc),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_grant_subset(actor.facts, _invitation_permissions(invitation))
        if invitation.delivery_status == "pending":
            raise AppError(
                code="project_invitation_delivery_pending",
                message="Invitation delivery is already pending",
                kind=FailureKind.CONFLICT,
            )
        now = datetime.now(timezone.utc)
        invitation.token_revision += 1
        invitation.invited_by_id = actor_id
        invitation.expires_at = now + INVITATION_TTL
        invitation.delivery_status = "pending"
        invitation.delivery_attempt_count = 0
        invitation.delivery_next_attempt_at = now
        invitation.delivery_lease_id = None
        invitation.delivery_lease_expires_at = None
        invitation.delivery_failure_code = None
        invitation.delivered_at = None
        db.flush()
        db.refresh(invitation)
        return invitation


project_repository = ProjectRepository()
