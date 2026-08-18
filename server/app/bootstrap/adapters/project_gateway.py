"""SQLAlchemy and external-service adapters for Project use cases."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.database.models import (
    AuthUser,
    Conversation,
    Document,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    ResearchItem,
)
from app.helpers.s3 import s3_service
from app.bootstrap.adapters.upload_repository import (
    upload_reservation_repository,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationDeliveryStatus,
    ProjectInvitationResponse,
    ProjectPaperSort,
    ProjectPaperSummaryResponse,
    ProjectPendingUploadResponse,
    ProjectPendingUploadsResponse,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectSort,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.projects.application.projects import (
    AcceptedProjectInvitation,
    ProjectCollaboratorUpdateResult,
    ProjectDeletion,
    ProjectDocumentCollection,
    ProjectPaperRemoval,
    ProjectPage,
    ProjectPageDirection,
    ProjectPagePosition,
    ProjectPaperPage,
    ProjectOutputPage,
    ProjectUpdateResult,
)
from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.bootstrap.adapters.project_presenters import project_response
from app.bootstrap.adapters.project_repository import project_repository
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from app.modules.papers.application.contracts.documents import LibraryOutputSort
from app.modules.papers.application.library import (
    LibraryPageDirection,
    LibraryPagePosition,
)
from app.bootstrap.adapters.library_outputs import SqlAlchemyLibraryOutputsGateway
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, load_only


def _collaborator_response(collaborator: object) -> ProjectCollaboratorResponse:
    from app.modules.projects.infrastructure.models import ProjectCollaborator

    if not isinstance(collaborator, ProjectCollaborator):
        raise TypeError("expected ProjectCollaborator")
    return ProjectCollaboratorResponse(
        user_id=collaborator.user_id,
        display_name=collaborator.user.display_name or collaborator.user.email,
        email=collaborator.user.email,
        is_owner=False,
        permissions=ProjectPermissionSet(
            edit_project=collaborator.can_edit_project,
            manage_papers=collaborator.can_manage_papers,
            manage_collaborators=collaborator.can_manage_collaborators,
        ),
        joined_at=collaborator.joined_at,
    )


class SqlAlchemyProjectGateway:
    def __init__(
        self,
        db: Session,
        *,
        invitation_tokens: ProjectInvitationTokenCodec,
    ) -> None:
        self._db = db
        self._invitation_tokens = invitation_tokens

    def _project(self, project: Project, *, user_id: int) -> ProjectResponse:
        return project_response(
            self._db,
            project=project,
            current_user_id=user_id,
        )

    def _invitation(self, invitation_id: UUID) -> ProjectInvitationResponse:
        invitation = self._db.get(ProjectInvitation, invitation_id)
        if invitation is None:
            raise RuntimeError("project_invitation_disappeared")
        project = self._db.get(Project, invitation.project_id)
        inviter = self._db.get(AuthUser, invitation.invited_by_id)
        if project is None or inviter is None:
            raise RuntimeError("project_invitation_relationship_missing")
        return ProjectInvitationResponse(
            id=invitation.id,
            project_id=invitation.project_id,
            project_name=project.title,
            email=invitation.email,
            invited_by=inviter.display_name or inviter.email,
            permissions=ProjectPermissionSet(
                edit_project=invitation.can_edit_project,
                manage_papers=invitation.can_manage_papers,
                manage_collaborators=invitation.can_manage_collaborators,
            ),
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
            delivery_status=ProjectInvitationDeliveryStatus(invitation.delivery_status),
            delivered_at=invitation.delivered_at,
        )

    def create(
        self,
        *,
        owner_id: int,
        request: ProjectCreateRequest,
    ) -> ProjectResponse:
        project = project_repository.create(
            self._db,
            owner_id=owner_id,
            title=request.title,
            description=request.description,
        )
        return self._project(project, user_id=owner_id)

    def list_projects(
        self,
        *,
        user_id: int,
        query: str | None,
        sort: ProjectSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPage:
        paper_count = (
            select(func.count(ProjectPaper.id))
            .where(ProjectPaper.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        conversation_count = (
            select(func.count(Conversation.id))
            .where(
                Conversation.project_id == Project.id,
                Conversation.scope_type == "project",
                Conversation.user_id == user_id,
            )
            .correlate(Project)
            .scalar_subquery()
        )
        output_count = (
            select(func.count(ResearchItem.id))
            .where(
                ResearchItem.audience_project_id == Project.id,
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            )
            .correlate(Project)
            .scalar_subquery()
        )
        collaborator_count = (
            select(func.count(ProjectCollaborator.id))
            .where(ProjectCollaborator.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        last_paper = (
            select(func.max(ProjectPaper.created_at))
            .where(ProjectPaper.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        last_conversation = (
            select(func.max(Conversation.updated_at))
            .where(
                Conversation.project_id == Project.id,
                Conversation.scope_type == "project",
                Conversation.user_id == user_id,
            )
            .correlate(Project)
            .scalar_subquery()
        )
        last_output = (
            select(func.max(ResearchItem.updated_at))
            .where(
                ResearchItem.audience_project_id == Project.id,
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            )
            .correlate(Project)
            .scalar_subquery()
        )
        activity = func.greatest(
            Project.updated_at,
            func.coalesce(last_paper, Project.updated_at),
            func.coalesce(last_conversation, Project.updated_at),
            func.coalesce(last_output, Project.updated_at),
        )
        membership_filter = or_(
            Project.owner_id == user_id,
            ProjectCollaborator.user_id == user_id,
        )
        filters = [membership_filter]
        if query is not None:
            pattern = f"%{query.lower()}%"
            filters.append(
                or_(
                    func.lower(Project.title).like(pattern),
                    func.lower(func.coalesce(Project.description, "")).like(pattern),
                )
            )
        key: Any
        if sort is ProjectSort.TITLE_ASC:
            key = func.lower(Project.title)
            cursor_key: object | None = position.key if position else None
            natural_ascending = True
        elif sort is ProjectSort.PAPERS_DESC:
            key = paper_count
            cursor_key = int(position.key) if position else None
            natural_ascending = False
        else:
            key = activity
            cursor_key = datetime.fromisoformat(position.key) if position else None
            natural_ascending = False
        effective_ascending = (
            natural_ascending
            if direction is ProjectPageDirection.FORWARD
            else not natural_ascending
        )
        if position is not None and cursor_key is not None:
            comparison = key > cursor_key if effective_ascending else key < cursor_key
            id_comparison = (
                Project.id > position.id
                if effective_ascending
                else Project.id < position.id
            )
            filters.append(or_(comparison, and_(key == cursor_key, id_comparison)))
        order = key.asc() if effective_ascending else key.desc()
        id_order = Project.id.asc() if effective_ascending else Project.id.desc()
        total_count = int(
            self._db.scalar(
                select(func.count(Project.id))
                .outerjoin(
                    ProjectCollaborator,
                    and_(
                        ProjectCollaborator.project_id == Project.id,
                        ProjectCollaborator.user_id == user_id,
                    ),
                )
                .where(*filters[: 2 if query is not None else 1])
            )
            or 0
        )
        statement = (
            select(
                Project,
                ProjectCollaborator,
                paper_count.label("num_papers"),
                conversation_count.label("num_conversations"),
                output_count.label("num_outputs"),
                collaborator_count.label("num_collaborators"),
                activity.label("activity_at"),
            )
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == user_id,
                ),
            )
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit + 1)
            .options(joinedload(Project.owner))
        )
        rows = list(self._db.execute(statement).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        items: list[ProjectResponse] = []
        positions: list[ProjectPagePosition] = []
        for row in rows:
            project = row.Project
            collaborator = row.ProjectCollaborator
            is_owner = project.owner_id == user_id
            permissions = ProjectPermissionSet(
                edit_project=is_owner or bool(collaborator.can_edit_project),
                manage_papers=is_owner or bool(collaborator.can_manage_papers),
                manage_collaborators=is_owner
                or bool(collaborator.can_manage_collaborators),
            )
            activity_at = row.activity_at
            items.append(
                ProjectResponse(
                    id=project.id,
                    title=project.title,
                    description=project.description,
                    owner=ProjectOwnerResponse(
                        id=project.owner.id,
                        display_name=project.owner.display_name or project.owner.email,
                        email=project.owner.email,
                    ),
                    membership=ProjectMembershipResponse(
                        kind="owner" if is_owner else "collaborator",
                        permissions=permissions,
                    ),
                    capabilities=ProjectCapabilitiesResponse(
                        edit_project=permissions.edit_project,
                        manage_papers=permissions.manage_papers,
                        manage_collaborators=permissions.manage_collaborators,
                        transfer=is_owner,
                        delete=is_owner,
                        leave=not is_owner,
                    ),
                    num_papers=int(row.num_papers),
                    num_conversations=int(row.num_conversations),
                    num_outputs=int(row.num_outputs),
                    num_collaborators=int(row.num_collaborators),
                    activity_at=activity_at,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )
            if sort is ProjectSort.TITLE_ASC:
                position_key = project.title.lower()
            elif sort is ProjectSort.PAPERS_DESC:
                position_key = str(int(row.num_papers))
            else:
                position_key = activity_at.isoformat()
            positions.append(ProjectPagePosition(key=position_key, id=project.id))
        return ProjectPage(
            items=items,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
        )

    def get(self, *, user_id: int, project_id: UUID) -> ProjectResponse:
        access = project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        return self._project(access.project, user_id=user_id)

    def update(
        self,
        *,
        user_id: int,
        project_id: UUID,
        request: ProjectUpdateRequest,
    ) -> ProjectUpdateResult:
        updated = project_repository.update(
            self._db,
            project_id=project_id,
            user_id=user_id,
            changes=request.model_dump(exclude_unset=True),
        )
        return ProjectUpdateResult(
            response=self._project(updated.project, user_id=user_id),
            changed=updated.changed,
        )

    def delete(
        self,
        *,
        user_id: int,
        project_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> ProjectDeletion:
        result = project_repository.delete(
            self._db,
            project_id=project_id,
            user_id=user_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )
        return ProjectDeletion(created_cleanup_job_ids=result.created_job_ids)

    def list_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ProjectCollaboratorResponse]:
        project, collaborators = project_repository.list_collaborators(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        owner = self._db.get(AuthUser, project.owner_id)
        if owner is None:
            raise RuntimeError("project_owner_missing")
        return [
            ProjectCollaboratorResponse(
                user_id=owner.id,
                display_name=owner.display_name or owner.email,
                email=owner.email,
                is_owner=True,
                permissions=ProjectPermissionSet(
                    edit_project=True,
                    manage_papers=True,
                    manage_collaborators=True,
                ),
                joined_at=project.created_at,
            ),
            *[_collaborator_response(item) for item in collaborators],
        ]

    def update_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
        request: ProjectCollaboratorUpdateRequest,
    ) -> ProjectCollaboratorUpdateResult:
        updated = project_repository.update_collaborator(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            target_user_id=user_id,
            requested=request,
        )
        return ProjectCollaboratorUpdateResult(
            response=_collaborator_response(updated.collaborator),
            changed=updated.changed,
        )

    def remove_member(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        user_id: int,
    ) -> None:
        project_repository.remove_collaborator(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            target_user_id=user_id,
        )

    def leave(self, *, user_id: int, project_id: UUID) -> None:
        project_repository.leave(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )

    def transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectResponse:
        project = project_repository.transfer(
            self._db,
            project_id=project_id,
            owner_id=owner_id,
            new_owner_id=request.new_owner_id,
        )
        return self._project(project, user_id=owner_id)

    def accept_invitation(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> AcceptedProjectInvitation:
        decoded = self._invitation_tokens.decode(raw_token)
        if decoded is None:
            raise AppError(
                code="project_invitation_invalid",
                message="Invitation is invalid or expired",
                kind=FailureKind.NOT_FOUND,
            )
        accepted = project_repository.accept_invitation(
            self._db,
            invitation_id=decoded.invitation_id,
            token_revision=decoded.revision,
            user_id=user_id,
            email=email,
        )
        return AcceptedProjectInvitation(
            project_id=accepted.collaborator.project_id,
            invitation_id=accepted.invitation_id,
        )

    def validate_invitation_token(
        self,
        *,
        raw_token: str,
        user_id: int,
        email: str,
    ) -> None:
        decoded = self._invitation_tokens.decode(raw_token)
        if decoded is None:
            raise AppError(
                code="project_invitation_invalid",
                message="Invitation is invalid or expired",
                kind=FailureKind.NOT_FOUND,
            )
        project_repository.validate_invitation(
            self._db,
            invitation_id=decoded.invitation_id,
            token_revision=decoded.revision,
            user_id=user_id,
            email=email,
        )

    def list_invitations(
        self,
        *,
        actor_id: int,
        project_id: UUID,
    ) -> list[ProjectInvitationResponse]:
        return [
            self._invitation(invitation.id)
            for invitation in project_repository.list_project_invitations(
                self._db,
                project_id=project_id,
                actor_id=actor_id,
            )
        ]

    def create_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> ProjectInvitationResponse:
        invitation = project_repository.create_invitation(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            email=str(request.email),
            requested=request,
        )
        return self._invitation(invitation.id)

    def resend_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse:
        invitation = project_repository.resend_invitation(
            self._db,
            project_id=project_id,
            invitation_id=invitation_id,
            actor_id=actor_id,
        )
        return self._invitation(invitation.id)

    def revoke_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> bool:
        return project_repository.revoke_invitation(
            self._db,
            project_id=project_id,
            invitation_id=invitation_id,
            actor_id=actor_id,
        )

    def collect_document(
        self,
        *,
        actor: Actor,
        request: CollectPaperFromProjectRequest,
    ) -> ProjectDocumentCollection | None:
        attached = project_document_repository.add_project_paper_to_library(
            self._db,
            document_id=request.document_id,
            project_id=request.source_project_id,
            current_user=actor,
        )
        if attached.document is None:
            return None
        return ProjectDocumentCollection(
            document_id=attached.document.id,
            added_to_library=attached.created,
        )

    def add_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        request: AddPaperToProjectRequest,
    ) -> tuple[int, int]:
        associations, existing_count = (
            project_document_repository.attach_library_documents(
                self._db,
                document_ids=request.document_ids,
                user=actor,
                project_id=project_id,
            )
        )
        return len(associations), existing_count

    def list_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        load_urls: bool,
        query: str | None,
        sort: ProjectPaperSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPaperPage:
        project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=actor.id,
        )
        filters = [ProjectPaper.project_id == project_id]
        if query is not None:
            pattern = f"%{query.lower()}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(Document.title, "")).like(pattern),
                    func.lower(func.coalesce(Document.abstract, "")).like(pattern),
                )
            )
        count_filters = tuple(filters)
        key: Any
        if sort is ProjectPaperSort.TITLE_ASC:
            key = func.lower(func.coalesce(Document.title, Document.original_filename))
            cursor_key: object | None = position.key if position else None
            natural_ascending = True
        elif sort is ProjectPaperSort.PUBLISHED_DESC:
            key = func.coalesce(
                Document.publish_date,
                datetime(1970, 1, 1, tzinfo=timezone.utc),
            )
            cursor_key = datetime.fromisoformat(position.key) if position else None
            natural_ascending = False
        else:
            key = ProjectPaper.created_at
            cursor_key = datetime.fromisoformat(position.key) if position else None
            natural_ascending = False
        effective_ascending = (
            natural_ascending
            if direction is ProjectPageDirection.FORWARD
            else not natural_ascending
        )
        if position is not None and cursor_key is not None:
            comparison = key > cursor_key if effective_ascending else key < cursor_key
            id_comparison = (
                ProjectPaper.id > position.id
                if effective_ascending
                else ProjectPaper.id < position.id
            )
            filters.append(or_(comparison, and_(key == cursor_key, id_comparison)))
        order = key.asc() if effective_ascending else key.desc()
        id_order = (
            ProjectPaper.id.asc() if effective_ascending else ProjectPaper.id.desc()
        )
        total_count = int(
            self._db.scalar(
                select(func.count(ProjectPaper.id))
                .join(Document, Document.id == ProjectPaper.document_id)
                .where(*count_filters)
            )
            or 0
        )
        statement = (
            select(ProjectPaper, Document)
            .join(Document, Document.id == ProjectPaper.document_id)
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit + 1)
            .options(
                load_only(ProjectPaper.id, ProjectPaper.created_at),
                load_only(
                    Document.id,
                    Document.title,
                    Document.original_filename,
                    Document.abstract,
                    Document.authors,
                    Document.institutions,
                    Document.journal,
                    Document.publisher,
                    Document.doi,
                    Document.publish_date,
                    Document.s3_object_key,
                ),
            )
        )
        rows = list(self._db.execute(statement).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        papers = [row.Document for row in rows]
        library_document_ids = set(
            project_document_repository.get_library_document_ids(
                self._db,
                document_ids=[paper.id for paper in papers],
                user=actor,
            )
        )
        file_urls = (
            s3_service.generate_presigned_urls(
                {str(paper.id): paper.s3_object_key for paper in papers}
            )
            if load_urls
            else {}
        )
        items = [
            ProjectPaperSummaryResponse(
                document_id=paper.id,
                title=paper.title,
                added_at=row.ProjectPaper.created_at,
                abstract=paper.abstract,
                authors=paper.authors,
                institutions=paper.institutions,
                status="reading",
                journal=paper.journal,
                publisher=paper.publisher,
                doi=paper.doi,
                publish_date=paper.publish_date,
                file_url=file_urls.get(str(paper.id)),
                in_library=paper.id in library_document_ids,
            )
            for row, paper in zip(rows, papers, strict=True)
        ]
        positions: list[ProjectPagePosition] = []
        for row in rows:
            association = row.ProjectPaper
            paper = row.Document
            if sort is ProjectPaperSort.TITLE_ASC:
                position_key = (paper.title or paper.original_filename).lower()
            elif sort is ProjectPaperSort.PUBLISHED_DESC:
                position_key = (
                    paper.publish_date or datetime(1970, 1, 1, tzinfo=timezone.utc)
                ).isoformat()
            else:
                position_key = association.created_at.isoformat()
            positions.append(ProjectPagePosition(key=position_key, id=association.id))
        return ProjectPaperPage(
            items=items,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
        )

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
    ) -> ProjectOutputPage:
        project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=actor.id,
        )
        page = SqlAlchemyLibraryOutputsGateway(self._db).list(
            user_id=actor.id,
            query=query,
            kinds=kinds,
            sort=sort,
            limit=limit,
            direction=LibraryPageDirection(direction.value),
            position=(
                LibraryPagePosition(key=position.key, id=position.id)
                if position is not None
                else None
            ),
            project_id=project_id,
        )
        return ProjectOutputPage(
            items=page.items,
            positions=[
                ProjectPagePosition(key=item.key, id=item.id) for item in page.positions
            ],
            has_more=page.has_more,
            total_count=page.total_count,
        )

    def pending_uploads(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ProjectPendingUploadsResponse:
        jobs = upload_reservation_repository.get_in_progress_jobs_for_project(
            self._db,
            project_id=project_id,
            user=actor,
        )
        return ProjectPendingUploadsResponse(
            items=[
                ProjectPendingUploadResponse(
                    job_id=job.id,
                    status=job.job.status,
                    document_id=document.id,
                    title=document.title,
                    started_at=job.job.started_at,
                )
                for job, document in jobs
            ]
        )

    def document_storage_key(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> str | None:
        document = project_document_repository.get_paper_by_project(
            self._db,
            document_id=document_id,
            project_id=project_id,
            user=actor,
        )
        return document.s3_object_key if document is not None else None

    def projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> list[ProjectResponse]:
        return [
            self._project(project, user_id=actor.id)
            for project in project_document_repository.get_projects_by_document_id(
                self._db,
                document_id=document_id,
                user=actor,
            )
        ]

    def remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> ProjectPaperRemoval:
        scheduled = project_document_repository.remove_by_paper_and_project(
            self._db,
            document_id=document_id,
            project_id=project_id,
            user=actor,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )
        return ProjectPaperRemoval(
            created_gc_job_id=(
                scheduled.job_id
                if scheduled is not None and scheduled.created
                else None
            )
        )
