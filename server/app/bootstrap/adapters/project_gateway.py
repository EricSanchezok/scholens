"""SQLAlchemy and external-service adapters for Project use cases."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload, load_only, selectinload

from app.bootstrap.adapters.library_outputs import SqlAlchemyLibraryOutputsGateway
from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.bootstrap.adapters.project_presenters import project_response
from app.bootstrap.adapters.project_repository import project_repository
from app.bootstrap.adapters.upload_repository import (
    upload_reservation_repository,
)
from app.database.models import (
    AnnotationComment,
    AnnotationThread,
    AuthUser,
    Conversation,
    Document,
    LibraryPaper,
    LibraryPaperTag,
    PaperTag,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    ResearchItem,
)
from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.documents import (
    LibraryOutputSort,
    LibraryPaperTagResponse,
)
from app.modules.papers.application.library import (
    LibraryPageDirection,
    LibraryPagePosition,
)
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_STORAGE_REFERENCE_COLUMNS,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCapabilitiesResponse,
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationDeliveryStatus,
    ProjectInvitationResponse,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPaperListResponse,
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
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.modules.projects.application.lifecycle import (
    ProjectDeletionPlan,
    ProjectInvitationCreationPlan,
    ProjectOwnershipTransferPlan,
    ProjectPaperRemovalPlan,
    ProjectPaperRemovalState,
)
from app.modules.projects.application.projects import (
    AcceptedProjectInvitation,
    ProjectCollaboratorUpdateResult,
    ProjectDeletion,
    ProjectDocumentCollection,
    ProjectInvitationPage,
    ProjectInvitationPagePosition,
    ProjectMemberPage,
    ProjectMemberPagePosition,
    ProjectOutputPage,
    ProjectPage,
    ProjectPageDirection,
    ProjectPagePosition,
    ProjectPaperPage,
    ProjectPaperRemoval,
    ProjectResourceCatalogItem,
    ProjectResourceMemberPage,
    ProjectResourcePage,
    ProjectResourcePaperPage,
    ProjectResourcePreview,
    ProjectSummaryPage,
    ProjectPaperSummaryPage,
    ProjectUpdateResult,
)
from app.modules.projects.application.summary_limits import (
    PROJECT_DESCRIPTION_JSON_BYTES,
    PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
    PROJECT_TEXT_JSON_BYTES,
)
from app.modules.projects.infrastructure.access import (
    require_project_permission_for_update,
)
from app.shared.application import Actor
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import PaperStatus, ResearchAudienceType, ResearchItemKind
from app.shared.infrastructure.sql_patterns import literal_contains_pattern

_RESOURCE_PROJECT_TITLE_CHARACTERS = PROJECT_TEXT_JSON_BYTES
_RESOURCE_PROJECT_DESCRIPTION_CHARACTERS = PROJECT_DESCRIPTION_JSON_BYTES
_RESOURCE_PROJECT_OWNER_NAME_CHARACTERS = 256
_RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS = 320
_RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS = PROJECT_TEXT_JSON_BYTES
_RESOURCE_PROJECT_PAPER_LONG_TEXT_CHARACTERS = PROJECT_PAPER_LONG_TEXT_JSON_BYTES
_ROW_PIVOT_CURSOR_PREFIX = "\x00row-v1:"


@dataclass(frozen=True, slots=True)
class _ProjectFacts:
    paper_count: Any
    conversation_count: Any
    output_count: Any
    collaborator_count: Any
    activity: Any


@dataclass(frozen=True, slots=True)
class _ProjectListPlan:
    facts: _ProjectFacts
    count_filters: tuple[Any, ...]
    page_filters: tuple[Any, ...]
    order: Any
    id_order: Any


@dataclass(frozen=True, slots=True)
class _ProjectPaperListPlan:
    count_filters: tuple[Any, ...]
    page_filters: tuple[Any, ...]
    order: Any
    id_order: Any


def _row_pivot_cursor_key(item_id: UUID) -> str:
    return f"{_ROW_PIVOT_CURSOR_PREFIX}{item_id}"


def _bounded_optional_row_text(value: str | None, *, max_bytes: int) -> str | None:
    return (
        json_bounded_prefix(value, max_bytes=max_bytes) if value is not None else None
    )


def _resource_project_filters(
    *,
    user_id: int,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
) -> list[Any]:
    filters: list[Any] = [
        or_(
            Project.owner_id == user_id,
            ProjectCollaborator.user_id == user_id,
        )
    ]
    if project_id is not None:
        filters.append(Project.id == project_id)
    if document_id is not None:
        filters.append(
            exists(
                select(ProjectPaper.id).where(
                    ProjectPaper.project_id == Project.id,
                    ProjectPaper.document_id == document_id,
                )
            )
        )
    return filters


def _resource_project_access_exists(*, user_id: int, project_id: UUID) -> Any:
    project_alias = aliased(Project)
    collaborator_alias = aliased(ProjectCollaborator)
    return exists(
        select(project_alias.id)
        .outerjoin(
            collaborator_alias,
            and_(
                collaborator_alias.project_id == project_alias.id,
                collaborator_alias.user_id == user_id,
            ),
        )
        .where(
            project_alias.id == project_id,
            or_(
                project_alias.owner_id == user_id,
                collaborator_alias.user_id == user_id,
            ),
        )
    )


def _project_facts(*, user_id: int) -> _ProjectFacts:
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
    return _ProjectFacts(
        paper_count=paper_count,
        conversation_count=conversation_count,
        output_count=output_count,
        collaborator_count=collaborator_count,
        activity=activity,
    )


def _project_list_plan(
    *,
    user_id: int,
    query: str | None,
    sort: ProjectSort,
    direction: ProjectPageDirection,
    position: ProjectPagePosition | None,
) -> _ProjectListPlan:
    facts = _project_facts(user_id=user_id)
    membership_filter = or_(
        Project.owner_id == user_id,
        ProjectCollaborator.user_id == user_id,
    )
    count_filters: list[Any] = [membership_filter]
    if query is not None:
        pattern = literal_contains_pattern(query.lower())
        count_filters.append(
            or_(
                func.lower(Project.title).like(pattern, escape="\\"),
                func.lower(func.coalesce(Project.description, "")).like(
                    pattern,
                    escape="\\",
                ),
            )
        )
    page_filters = list(count_filters)
    if sort is ProjectSort.TITLE_ASC:
        key = func.lower(Project.title)
        cursor_key: object | None = position.key if position else None
        natural_ascending = True
    elif sort is ProjectSort.PAPERS_DESC:
        key = facts.paper_count
        cursor_key = int(position.key) if position else None
        natural_ascending = False
    else:
        key = facts.activity
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
        page_filters.append(or_(comparison, and_(key == cursor_key, id_comparison)))
    return _ProjectListPlan(
        facts=facts,
        count_filters=tuple(count_filters),
        page_filters=tuple(page_filters),
        order=key.asc() if effective_ascending else key.desc(),
        id_order=Project.id.asc() if effective_ascending else Project.id.desc(),
    )


def _project_paper_list_plan(
    *,
    actor_id: int,
    project_id: UUID,
    query: str | None,
    personal_statuses: tuple[PaperStatus, ...],
    personal_tag_ids: tuple[UUID, ...],
    sort: ProjectPaperSort,
    direction: ProjectPageDirection,
    position: ProjectPagePosition | None,
) -> _ProjectPaperListPlan:
    count_filters: list[Any] = [ProjectPaper.project_id == project_id]
    if query is not None:
        pattern = literal_contains_pattern(query.lower())
        count_filters.append(
            or_(
                func.lower(func.coalesce(Document.title, "")).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(func.coalesce(Document.abstract, "")).like(
                    pattern,
                    escape="\\",
                ),
            )
        )
    if personal_statuses:
        count_filters.append(
            LibraryPaper.status.in_([status.value for status in personal_statuses])
        )
    if personal_tag_ids:
        count_filters.append(
            LibraryPaper.id.in_(
                select(LibraryPaperTag.library_paper_id)
                .join(PaperTag, PaperTag.id == LibraryPaperTag.tag_id)
                .where(
                    LibraryPaperTag.tag_id.in_(personal_tag_ids),
                    PaperTag.user_id == actor_id,
                )
            )
        )
    page_filters = list(count_filters)
    key: Any
    if sort is ProjectPaperSort.PERSONAL_ACTIVITY_DESC:
        key = func.coalesce(
            LibraryPaper.last_accessed_at,
            ProjectPaper.created_at,
        )
        cursor_key: object | None = (
            datetime.fromisoformat(position.key) if position else None
        )
        natural_ascending = False
    elif sort is ProjectPaperSort.TITLE_ASC:
        key = func.lower(func.coalesce(Document.title, Document.original_filename))
        if position is not None and position.key == _row_pivot_cursor_key(position.id):
            pivot_paper = aliased(ProjectPaper)
            pivot_document = aliased(Document)
            cursor_key = (
                select(
                    func.lower(
                        func.coalesce(
                            pivot_document.title,
                            pivot_document.original_filename,
                        )
                    )
                )
                .join(
                    pivot_document,
                    pivot_document.id == pivot_paper.document_id,
                )
                .where(pivot_paper.id == position.id)
                .scalar_subquery()
            )
        else:
            cursor_key = position.key if position else None
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
        page_filters.append(or_(comparison, and_(key == cursor_key, id_comparison)))
    return _ProjectPaperListPlan(
        count_filters=tuple(count_filters),
        page_filters=tuple(page_filters),
        order=key.asc() if effective_ascending else key.desc(),
        id_order=(
            ProjectPaper.id.asc() if effective_ascending else ProjectPaper.id.desc()
        ),
    )


def _bounded_project_resource_statement(
    *,
    user_id: int,
    facts: _ProjectFacts | None = None,
) -> Any:
    """Select fixed-size Project fields and scalar aggregate facts only."""

    facts = facts or _project_facts(user_id=user_id)
    owner_email = case(
        (
            func.char_length(AuthUser.email)
            <= _RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS,
            AuthUser.email,
        ),
        else_=func.concat(
            "project-owner-",
            cast(AuthUser.id, Text),
            "@example.com",
        ),
    )
    owner_display_name = func.coalesce(
        func.nullif(func.btrim(AuthUser.display_name), ""),
        owner_email,
    )
    content_truncated = or_(
        func.char_length(Project.title) > _RESOURCE_PROJECT_TITLE_CHARACTERS,
        func.coalesce(func.char_length(cast(Project.description, Text)), 0)
        > _RESOURCE_PROJECT_DESCRIPTION_CHARACTERS,
        func.char_length(owner_display_name) > _RESOURCE_PROJECT_OWNER_NAME_CHARACTERS,
        func.char_length(AuthUser.email) > _RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS,
    )
    return (
        select(
            Project.id,
            func.left(
                cast(Project.title, Text),
                _RESOURCE_PROJECT_TITLE_CHARACTERS,
            ).label("title"),
            func.left(
                cast(Project.description, Text),
                _RESOURCE_PROJECT_DESCRIPTION_CHARACTERS,
            ).label("description"),
            Project.owner_id,
            func.left(
                cast(owner_display_name, Text),
                _RESOURCE_PROJECT_OWNER_NAME_CHARACTERS,
            ).label("owner_display_name"),
            owner_email.label("owner_email"),
            ProjectCollaborator.can_edit_project,
            ProjectCollaborator.can_manage_papers,
            ProjectCollaborator.can_manage_collaborators,
            facts.paper_count.label("num_papers"),
            facts.conversation_count.label("num_conversations"),
            facts.output_count.label("num_outputs"),
            facts.collaborator_count.label("num_collaborators"),
            facts.activity.label("activity_at"),
            Project.created_at,
            Project.updated_at,
            content_truncated.label("content_truncated"),
        )
        .join(AuthUser, AuthUser.id == Project.owner_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )


def _resource_project_preview(*, row: Any, user_id: int) -> ProjectResourcePreview:
    title = json_bounded_prefix(row.title, max_bytes=PROJECT_TEXT_JSON_BYTES)
    description = (
        json_bounded_prefix(
            row.description,
            max_bytes=PROJECT_DESCRIPTION_JSON_BYTES,
        )
        if row.description is not None
        else None
    )
    owner_display_name = json_bounded_prefix(
        row.owner_display_name,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    owner_email_prefix = json_bounded_prefix(
        row.owner_email,
        max_bytes=_RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS,
    )
    owner_email = (
        row.owner_email
        if owner_email_prefix == row.owner_email
        else f"project-owner-{row.owner_id}@example.com"
    )
    text_truncated = (
        title != row.title
        or description != row.description
        or owner_display_name != row.owner_display_name
        or owner_email != row.owner_email
    )
    is_owner = row.owner_id == user_id
    permissions = ProjectPermissionSet(
        edit_project=is_owner or bool(row.can_edit_project),
        manage_papers=is_owner or bool(row.can_manage_papers),
        manage_collaborators=is_owner or bool(row.can_manage_collaborators),
    )
    return ProjectResourcePreview(
        value=ProjectResponse(
            id=row.id,
            title=title,
            description=description,
            owner=ProjectOwnerResponse(
                id=row.owner_id,
                display_name=owner_display_name,
                email=owner_email,
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
            activity_at=row.activity_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        ),
        content_truncated=bool(row.content_truncated) or text_truncated,
    )


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


def _owner_collaborator_response(
    project: Project,
    owner: AuthUser,
) -> ProjectCollaboratorResponse:
    return ProjectCollaboratorResponse(
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

    def _invitation(
        self,
        invitation_or_id: ProjectInvitation | UUID,
    ) -> ProjectInvitationResponse:
        invitation: ProjectInvitation
        project: Project | None
        inviter: AuthUser | None
        if isinstance(invitation_or_id, ProjectInvitation):
            invitation = invitation_or_id
            project = invitation.project
            inviter = invitation.invited_by
        else:
            loaded_invitation = self._db.get(ProjectInvitation, invitation_or_id)
            if loaded_invitation is None:
                raise RuntimeError("project_invitation_disappeared")
            invitation = loaded_invitation
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
        plan = _project_list_plan(
            user_id=user_id,
            query=query,
            sort=sort,
            direction=direction,
            position=position,
        )
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
                .where(*plan.count_filters)
            )
            or 0
        )
        statement = (
            select(
                Project,
                ProjectCollaborator,
                plan.facts.paper_count.label("num_papers"),
                plan.facts.conversation_count.label("num_conversations"),
                plan.facts.output_count.label("num_outputs"),
                plan.facts.collaborator_count.label("num_collaborators"),
                plan.facts.activity.label("activity_at"),
            )
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == user_id,
                ),
            )
            .where(*plan.page_filters)
            .order_by(plan.order, plan.id_order)
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

    def list_project_summaries(
        self,
        *,
        user_id: int,
        query: str | None,
        sort: ProjectSort,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectSummaryPage:
        plan = _project_list_plan(
            user_id=user_id,
            query=query,
            sort=sort,
            direction=direction,
            position=position,
        )
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
                .where(*plan.count_filters)
            )
            or 0
        )
        rows = list(
            self._db.execute(
                _bounded_project_resource_statement(
                    user_id=user_id,
                    facts=plan.facts,
                )
                .where(*plan.page_filters)
                .order_by(plan.order, plan.id_order)
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        previews = [_resource_project_preview(row=row, user_id=user_id) for row in rows]
        positions: list[ProjectPagePosition] = []
        for row in rows:
            if sort is ProjectSort.TITLE_ASC:
                position_key = row.title.lower()
            elif sort is ProjectSort.PAPERS_DESC:
                position_key = str(int(row.num_papers))
            else:
                position_key = row.activity_at.isoformat()
            positions.append(ProjectPagePosition(key=position_key, id=row.id))
        return ProjectSummaryPage(
            items=previews,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
        )

    def list_resource_projects(
        self,
        *,
        user_id: int,
        limit: int,
        document_id: UUID | None = None,
    ) -> ProjectResourcePage:
        filters = _resource_project_filters(
            user_id=user_id,
            document_id=document_id,
        )
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
                .where(*filters)
            )
            or 0
        )
        rows = list(
            self._db.execute(
                _bounded_project_resource_statement(user_id=user_id)
                .where(*filters)
                .order_by(Project.updated_at.desc(), Project.id.desc())
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        return ProjectResourcePage(
            items=[
                _resource_project_preview(row=row, user_id=user_id)
                for row in rows[:limit]
            ],
            has_more=has_more,
            total_count=total_count,
        )

    def list_resource_catalog(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[ProjectResourceCatalogItem]:
        rows = self._db.execute(
            select(
                Project.id,
                func.left(
                    cast(Project.title, Text),
                    _RESOURCE_PROJECT_TITLE_CHARACTERS,
                ).label("title"),
            )
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == user_id,
                ),
            )
            .where(
                or_(
                    Project.owner_id == user_id,
                    ProjectCollaborator.user_id == user_id,
                )
            )
            .order_by(Project.updated_at.desc(), Project.id.desc())
            .limit(limit)
        ).all()
        return [ProjectResourceCatalogItem(id=row.id, title=row.title) for row in rows]

    def get_resource_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> ProjectResourcePreview | None:
        row = self._db.execute(
            _bounded_project_resource_statement(user_id=user_id).where(
                *_resource_project_filters(
                    user_id=user_id,
                    project_id=project_id,
                )
            )
        ).one_or_none()
        return (
            _resource_project_preview(row=row, user_id=user_id)
            if row is not None
            else None
        )

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
    ) -> ProjectPaperSummaryPage:
        if self.get_resource_project(user_id=actor.id, project_id=project_id) is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        plan = _project_paper_list_plan(
            actor_id=actor.id,
            project_id=project_id,
            query=query,
            personal_statuses=personal_statuses,
            personal_tag_ids=personal_tag_ids,
            sort=sort,
            direction=direction,
            position=position,
        )
        total_count = int(
            self._db.scalar(
                select(func.count(ProjectPaper.id))
                .join(Document, Document.id == ProjectPaper.document_id)
                .outerjoin(
                    LibraryPaper,
                    and_(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                    ),
                )
                .where(*plan.count_filters)
            )
            or 0
        )
        personal_tags_exist = exists(
            select(LibraryPaperTag.library_paper_id).where(
                LibraryPaperTag.library_paper_id == LibraryPaper.id
            )
        )
        content_truncated = or_(
            func.coalesce(func.char_length(cast(Document.title, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
            func.coalesce(func.char_length(cast(Document.abstract, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_LONG_TEXT_CHARACTERS,
            func.coalesce(func.char_length(cast(Document.journal, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
            func.coalesce(func.char_length(cast(Document.publisher, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
            func.coalesce(func.char_length(cast(Document.doi, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
            func.coalesce(func.char_length(cast(Document.summary, Text)), 0)
            > _RESOURCE_PROJECT_PAPER_LONG_TEXT_CHARACTERS,
            Document.authors.is_not(None),
            Document.institutions.is_not(None),
            Document.keywords.is_not(None),
            personal_tags_exist,
        )
        rows = list(
            self._db.execute(
                select(
                    ProjectPaper.id.label("association_id"),
                    Document.id.label("document_id"),
                    func.left(
                        cast(Document.title, Text),
                        _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
                    ).label("title"),
                    ProjectPaper.created_at.label("added_at"),
                    func.left(
                        cast(Document.abstract, Text),
                        _RESOURCE_PROJECT_PAPER_LONG_TEXT_CHARACTERS,
                    ).label("abstract"),
                    func.left(
                        cast(Document.journal, Text),
                        _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
                    ).label("journal"),
                    func.left(
                        cast(Document.publisher, Text),
                        _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
                    ).label("publisher"),
                    func.left(
                        cast(Document.doi, Text),
                        _RESOURCE_PROJECT_PAPER_TEXT_CHARACTERS,
                    ).label("doi"),
                    Document.publish_date,
                    func.left(
                        cast(Document.summary, Text),
                        _RESOURCE_PROJECT_PAPER_LONG_TEXT_CHARACTERS,
                    ).label("summary"),
                    LibraryPaper.id.label("library_entry_id"),
                    LibraryPaper.status.label("personal_status"),
                    LibraryPaper.last_accessed_at.label("personal_last_accessed_at"),
                    content_truncated.label("content_truncated"),
                )
                .select_from(ProjectPaper)
                .join(Document, Document.id == ProjectPaper.document_id)
                .outerjoin(
                    LibraryPaper,
                    and_(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                    ),
                )
                .where(*plan.page_filters)
                .order_by(plan.order, plan.id_order)
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        items: list[ProjectPaperSummaryResponse] = []
        positions: list[ProjectPagePosition] = []
        truncated = False
        for row in rows:
            title = _bounded_optional_row_text(
                row.title,
                max_bytes=PROJECT_TEXT_JSON_BYTES,
            )
            abstract = _bounded_optional_row_text(
                row.abstract,
                max_bytes=PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
            )
            journal = _bounded_optional_row_text(
                row.journal,
                max_bytes=PROJECT_TEXT_JSON_BYTES,
            )
            publisher = _bounded_optional_row_text(
                row.publisher,
                max_bytes=PROJECT_TEXT_JSON_BYTES,
            )
            doi = _bounded_optional_row_text(
                row.doi,
                max_bytes=PROJECT_TEXT_JSON_BYTES,
            )
            summary = _bounded_optional_row_text(
                row.summary,
                max_bytes=PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
            )
            bounded_values = (title, abstract, journal, publisher, doi, summary)
            source_values = (
                row.title,
                row.abstract,
                row.journal,
                row.publisher,
                row.doi,
                row.summary,
            )
            truncated = (
                truncated
                or bool(row.content_truncated)
                or bounded_values != source_values
            )
            items.append(
                ProjectPaperSummaryResponse(
                    document_id=row.document_id,
                    title=title,
                    added_at=row.added_at,
                    abstract=abstract,
                    authors=None,
                    institutions=None,
                    status="reading",
                    journal=journal,
                    publisher=publisher,
                    doi=doi,
                    publish_date=row.publish_date,
                    file_url=None,
                    preview_url=None,
                    summary=summary,
                    keywords=[],
                    in_library=row.library_entry_id is not None,
                    personal_status=row.personal_status,
                    personal_tags=[],
                    personal_last_accessed_at=row.personal_last_accessed_at,
                )
            )
            if sort is ProjectPaperSort.PERSONAL_ACTIVITY_DESC:
                position_key = (
                    row.personal_last_accessed_at or row.added_at
                ).isoformat()
            elif sort is ProjectPaperSort.TITLE_ASC:
                position_key = _row_pivot_cursor_key(row.association_id)
            elif sort is ProjectPaperSort.PUBLISHED_DESC:
                position_key = (
                    row.publish_date or datetime(1970, 1, 1, tzinfo=timezone.utc)
                ).isoformat()
            else:
                position_key = row.added_at.isoformat()
            positions.append(
                ProjectPagePosition(key=position_key, id=row.association_id)
            )
        return ProjectPaperSummaryPage(
            items=items,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
            content_truncated=truncated,
        )

    def list_resource_documents(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourcePaperPage:
        page = self.list_document_summaries(
            actor=actor,
            project_id=project_id,
            query=None,
            personal_statuses=(),
            personal_tag_ids=(),
            sort=ProjectPaperSort.ADDED_DESC,
            limit=limit,
            direction=ProjectPageDirection.FORWARD,
            position=None,
        )
        return ProjectResourcePaperPage(
            value=ProjectPaperListResponse(
                items=page.items,
                total_count=page.total_count,
            ),
            content_truncated=page.content_truncated or page.has_more,
        )

    def list_resource_members(
        self,
        *,
        user_id: int,
        project_id: UUID,
        limit: int,
    ) -> ProjectResourceMemberPage:
        project_preview = self.get_resource_project(
            user_id=user_id,
            project_id=project_id,
        )
        if project_preview is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                kind=FailureKind.NOT_FOUND,
            )
        access_exists = _resource_project_access_exists(
            user_id=user_id,
            project_id=project_id,
        )
        total_count = 1 + int(
            self._db.scalar(
                select(func.count(ProjectCollaborator.id)).where(
                    ProjectCollaborator.project_id == project_id,
                    access_exists,
                )
            )
            or 0
        )
        owner = project_preview.value.owner
        items = [
            ProjectCollaboratorResponse(
                user_id=owner.id,
                display_name=owner.display_name,
                email=owner.email,
                is_owner=True,
                permissions=ProjectPermissionSet(
                    edit_project=True,
                    manage_papers=True,
                    manage_collaborators=True,
                ),
                joined_at=project_preview.value.created_at,
            )
        ]
        rows: list[Any] = []
        collaborator_slots = limit - 1
        if collaborator_slots > 0:
            member_email = case(
                (
                    func.char_length(AuthUser.email)
                    <= _RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS,
                    AuthUser.email,
                ),
                else_=func.concat(
                    "project-member-",
                    cast(AuthUser.id, Text),
                    "@example.com",
                ),
            )
            member_display_name = func.coalesce(
                func.nullif(func.btrim(AuthUser.display_name), ""),
                member_email,
            )
            rows = list(
                self._db.execute(
                    select(
                        ProjectCollaborator.user_id,
                        func.left(
                            cast(member_display_name, Text),
                            _RESOURCE_PROJECT_OWNER_NAME_CHARACTERS,
                        ).label("display_name"),
                        member_email.label("email"),
                        ProjectCollaborator.can_edit_project,
                        ProjectCollaborator.can_manage_papers,
                        ProjectCollaborator.can_manage_collaborators,
                        ProjectCollaborator.joined_at,
                        or_(
                            func.char_length(member_display_name)
                            > _RESOURCE_PROJECT_OWNER_NAME_CHARACTERS,
                            func.char_length(AuthUser.email)
                            > _RESOURCE_PROJECT_OWNER_EMAIL_CHARACTERS,
                        ).label("content_truncated"),
                    )
                    .join(AuthUser, AuthUser.id == ProjectCollaborator.user_id)
                    .where(
                        ProjectCollaborator.project_id == project_id,
                        access_exists,
                    )
                    .order_by(
                        ProjectCollaborator.joined_at.asc(),
                        ProjectCollaborator.user_id.asc(),
                    )
                    .limit(collaborator_slots)
                ).all()
            )
            items.extend(
                ProjectCollaboratorResponse(
                    user_id=row.user_id,
                    display_name=row.display_name,
                    email=row.email,
                    is_owner=False,
                    permissions=ProjectPermissionSet(
                        edit_project=bool(row.can_edit_project),
                        manage_papers=bool(row.can_manage_papers),
                        manage_collaborators=bool(row.can_manage_collaborators),
                    ),
                    joined_at=row.joined_at,
                )
                for row in rows
            )
        return ProjectResourceMemberPage(
            value=ProjectCollaboratorListResponse(
                items=items,
                total_count=total_count,
            ),
            content_truncated=(
                project_preview.content_truncated
                or total_count > len(items)
                or any(bool(row.content_truncated) for row in rows)
            ),
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
        plan: ProjectDeletionPlan | None = None,
    ) -> ProjectDeletion:
        result = project_repository.delete(
            self._db,
            project_id=project_id,
            user_id=user_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
            plan=plan,
        )
        return ProjectDeletion(
            created_cleanup_job_count=result.created_job_count,
            created_cleanup_job_ids=result.created_job_ids,
        )

    def plan_delete(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> ProjectDeletionPlan:
        return project_repository.plan_delete(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )

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
            _owner_collaborator_response(project, owner),
            *[_collaborator_response(item) for item in collaborators],
        ]

    def list_members_page(
        self,
        *,
        user_id: int,
        project_id: UUID,
        limit: int,
        position: ProjectMemberPagePosition | None,
    ) -> ProjectMemberPage:
        access = project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        project = access.project
        owner = self._db.get(AuthUser, project.owner_id)
        if owner is None:
            raise RuntimeError("project_owner_missing")
        total_count = 1 + int(
            self._db.scalar(
                select(func.count(ProjectCollaborator.id)).where(
                    ProjectCollaborator.project_id == project_id
                )
            )
            or 0
        )

        filters = [ProjectCollaborator.project_id == project_id]
        include_owner = position is None
        if position is not None:
            if position.kind == "owner":
                if position.user_id != owner.id:
                    raise AppError(
                        code="project_cursor_invalid",
                        message="The Project cursor is invalid or expired",
                        kind=FailureKind.INVALID_ARGUMENT,
                    )
            else:
                joined_at = datetime.fromisoformat(position.key)
                filters.append(
                    or_(
                        ProjectCollaborator.joined_at > joined_at,
                        and_(
                            ProjectCollaborator.joined_at == joined_at,
                            ProjectCollaborator.user_id > position.user_id,
                        ),
                    )
                )

        collaborators = list(
            self._db.scalars(
                select(ProjectCollaborator)
                .where(*filters)
                .options(joinedload(ProjectCollaborator.user))
                .order_by(
                    ProjectCollaborator.joined_at.asc(),
                    ProjectCollaborator.user_id.asc(),
                )
                .limit(limit + 1)
            ).all()
        )
        items: list[ProjectCollaboratorResponse] = []
        positions: list[ProjectMemberPagePosition] = []
        if include_owner:
            items.append(_owner_collaborator_response(project, owner))
            positions.append(
                ProjectMemberPagePosition(
                    kind="owner",
                    key="",
                    user_id=owner.id,
                )
            )
        for collaborator in collaborators:
            items.append(_collaborator_response(collaborator))
            positions.append(
                ProjectMemberPagePosition(
                    kind="collaborator",
                    key=collaborator.joined_at.isoformat(),
                    user_id=collaborator.user_id,
                )
            )
        has_more = len(items) > limit
        return ProjectMemberPage(
            items=items[:limit],
            positions=positions[:limit],
            has_more=has_more,
            total_count=total_count,
        )

    def get_member(
        self,
        *,
        user_id: int,
        project_id: UUID,
        target_user_id: int,
    ) -> ProjectCollaboratorResponse:
        access = project_repository.get_access(
            self._db,
            project_id=project_id,
            user_id=user_id,
        )
        project = access.project
        if target_user_id == project.owner_id:
            owner = self._db.get(AuthUser, project.owner_id)
            if owner is None:
                raise RuntimeError("project_owner_missing")
            return _owner_collaborator_response(project, owner)
        collaborator = self._db.scalar(
            select(ProjectCollaborator)
            .where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == target_user_id,
            )
            .options(joinedload(ProjectCollaborator.user))
        )
        if collaborator is None:
            raise AppError(
                code="project_collaborator_not_found",
                message="Project collaborator not found",
                kind=FailureKind.NOT_FOUND,
            )
        return _collaborator_response(collaborator)

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
        plan: ProjectOwnershipTransferPlan | None = None,
    ) -> ProjectResponse:
        project = project_repository.transfer(
            self._db,
            project_id=project_id,
            owner_id=owner_id,
            new_owner_id=request.new_owner_id,
            plan=plan,
        )
        return self._project(project, user_id=owner_id)

    def plan_transfer(
        self,
        *,
        owner_id: int,
        project_id: UUID,
        request: ProjectTransferRequest,
    ) -> ProjectOwnershipTransferPlan:
        return project_repository.plan_transfer(
            self._db,
            project_id=project_id,
            owner_id=owner_id,
            new_owner_id=request.new_owner_id,
        )

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
            self._invitation(invitation)
            for invitation in project_repository.list_project_invitations(
                self._db,
                project_id=project_id,
                actor_id=actor_id,
            )
        ]

    def list_invitations_page(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        limit: int,
        position: ProjectInvitationPagePosition | None,
    ) -> ProjectInvitationPage:
        invitations = project_repository.list_project_invitations_page(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            limit=limit,
            position_created_at=position.created_at if position is not None else None,
            position_id=position.id if position is not None else None,
        )
        has_more = len(invitations) > limit
        invitations = invitations[:limit]
        return ProjectInvitationPage(
            items=[self._invitation(invitation) for invitation in invitations],
            positions=[
                ProjectInvitationPagePosition(
                    created_at=invitation.created_at,
                    id=invitation.id,
                )
                for invitation in invitations
            ],
            has_more=has_more,
        )

    def get_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        invitation_id: UUID,
    ) -> ProjectInvitationResponse | None:
        invitation = project_repository.get_project_invitation(
            self._db,
            project_id=project_id,
            invitation_id=invitation_id,
            actor_id=actor_id,
        )
        return self._invitation(invitation) if invitation is not None else None

    def create_invitation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
        plan: ProjectInvitationCreationPlan | None = None,
    ) -> ProjectInvitationResponse:
        invitation = project_repository.create_invitation(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            email=str(request.email),
            requested=request,
            plan=plan,
        )
        return self._invitation(invitation.id)

    def plan_invitation_creation(
        self,
        *,
        actor_id: int,
        project_id: UUID,
        request: ProjectInvitationCreateRequest,
    ) -> ProjectInvitationCreationPlan:
        return project_repository.plan_invitation_creation(
            self._db,
            project_id=project_id,
            actor_id=actor_id,
            email=str(request.email),
            requested=request,
        )

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
        load_preview_urls: bool,
        query: str | None,
        personal_statuses: tuple[PaperStatus, ...],
        personal_tag_ids: tuple[UUID, ...],
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
        plan = _project_paper_list_plan(
            actor_id=actor.id,
            project_id=project_id,
            query=query,
            personal_statuses=personal_statuses,
            personal_tag_ids=personal_tag_ids,
            sort=sort,
            direction=direction,
            position=position,
        )
        total_count = int(
            self._db.scalar(
                select(func.count(ProjectPaper.id))
                .join(Document, Document.id == ProjectPaper.document_id)
                .outerjoin(
                    LibraryPaper,
                    and_(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                    ),
                )
                .where(*plan.count_filters)
            )
            or 0
        )
        statement = (
            select(ProjectPaper, Document, LibraryPaper)
            .join(Document, Document.id == ProjectPaper.document_id)
            .outerjoin(
                LibraryPaper,
                and_(
                    LibraryPaper.document_id == Document.id,
                    LibraryPaper.user_id == actor.id,
                ),
            )
            .where(*plan.page_filters)
            .order_by(plan.order, plan.id_order)
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
                    Document.preview_s3_key,
                    Document.summary,
                    Document.keywords,
                ),
                selectinload(LibraryPaper.tags),
            )
        )
        rows = list(self._db.execute(statement).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        papers = [row.Document for row in rows]
        file_urls = (
            s3_service.generate_presigned_urls(
                {str(paper.id): paper.s3_object_key for paper in papers}
            )
            if load_urls
            else {}
        )
        preview_urls = (
            s3_service.generate_presigned_urls(
                {
                    str(paper.id): paper.preview_s3_key
                    for paper in papers
                    if paper.preview_s3_key
                }
            )
            if load_preview_urls
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
                # Preserve the historical project-paper field for existing
                # HTTP and MCP consumers. Personal reading state is additive
                # and belongs exclusively to ``personal_status`` below.
                status="reading",
                journal=paper.journal,
                publisher=paper.publisher,
                doi=paper.doi,
                publish_date=paper.publish_date,
                file_url=file_urls.get(str(paper.id)),
                preview_url=preview_urls.get(str(paper.id)),
                summary=paper.summary,
                keywords=paper.keywords or [],
                in_library=library_entry is not None,
                personal_status=(
                    library_entry.status if library_entry is not None else None
                ),
                personal_tags=(
                    [
                        LibraryPaperTagResponse(
                            id=tag.id,
                            name=tag.name,
                            color=tag.color,
                        )
                        for tag in library_entry.tags
                    ]
                    if library_entry is not None
                    else []
                ),
                personal_last_accessed_at=(
                    library_entry.last_accessed_at
                    if library_entry is not None
                    else None
                ),
            )
            for row, paper, library_entry in (
                (row, row.Document, row.LibraryPaper) for row in rows
            )
        ]
        positions: list[ProjectPagePosition] = []
        for row in rows:
            association = row.ProjectPaper
            paper = row.Document
            library_entry = row.LibraryPaper
            if sort is ProjectPaperSort.PERSONAL_ACTIVITY_DESC:
                position_key = (
                    library_entry.last_accessed_at
                    if library_entry is not None
                    else association.created_at
                ).isoformat()
            elif sort is ProjectPaperSort.TITLE_ASC:
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
        maximum_payload_json_bytes: int | None = None,
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
            maximum_payload_json_bytes=maximum_payload_json_bytes,
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
            document_columns=DOCUMENT_STORAGE_REFERENCE_COLUMNS,
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

    def list_projects_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectPage:
        membership = or_(
            Project.owner_id == actor.id,
            ProjectCollaborator.user_id == actor.id,
        )
        base_filters = (
            ProjectPaper.document_id == document_id,
            membership,
        )
        total_count = int(
            self._db.scalar(
                select(func.count(Project.id))
                .join(ProjectPaper, ProjectPaper.project_id == Project.id)
                .outerjoin(
                    ProjectCollaborator,
                    and_(
                        ProjectCollaborator.project_id == Project.id,
                        ProjectCollaborator.user_id == actor.id,
                    ),
                )
                .where(*base_filters)
            )
            or 0
        )
        effective_ascending = direction is ProjectPageDirection.FORWARD
        filters = list(base_filters)
        if position is not None:
            filters.append(
                Project.id > position.id
                if effective_ascending
                else Project.id < position.id
            )
        statement = (
            select(Project)
            .join(ProjectPaper, ProjectPaper.project_id == Project.id)
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == actor.id,
                ),
            )
            .where(*filters)
            .order_by(Project.id.asc() if effective_ascending else Project.id.desc())
            .limit(limit + 1)
            .options(joinedload(Project.owner))
        )
        projects = list(self._db.scalars(statement).all())
        has_more = len(projects) > limit
        projects = projects[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            projects.reverse()
        return ProjectPage(
            items=[self._project(project, user_id=actor.id) for project in projects],
            positions=[
                ProjectPagePosition(key=str(project.id), id=project.id)
                for project in projects
            ],
            has_more=has_more,
            total_count=total_count,
        )

    def list_project_summaries_for_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        limit: int,
        direction: ProjectPageDirection,
        position: ProjectPagePosition | None,
    ) -> ProjectSummaryPage:
        membership = or_(
            Project.owner_id == actor.id,
            ProjectCollaborator.user_id == actor.id,
        )
        count_filters = (
            ProjectPaper.document_id == document_id,
            membership,
        )
        total_count = int(
            self._db.scalar(
                select(func.count(Project.id))
                .join(ProjectPaper, ProjectPaper.project_id == Project.id)
                .outerjoin(
                    ProjectCollaborator,
                    and_(
                        ProjectCollaborator.project_id == Project.id,
                        ProjectCollaborator.user_id == actor.id,
                    ),
                )
                .where(*count_filters)
            )
            or 0
        )
        effective_ascending = direction is ProjectPageDirection.FORWARD
        page_filters = list(count_filters)
        if position is not None:
            page_filters.append(
                Project.id > position.id
                if effective_ascending
                else Project.id < position.id
            )
        rows = list(
            self._db.execute(
                _bounded_project_resource_statement(user_id=actor.id)
                .join(ProjectPaper, ProjectPaper.project_id == Project.id)
                .where(*page_filters)
                .order_by(
                    Project.id.asc() if effective_ascending else Project.id.desc()
                )
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is ProjectPageDirection.BACKWARD:
            rows.reverse()
        return ProjectSummaryPage(
            items=[
                _resource_project_preview(row=row, user_id=actor.id) for row in rows
            ],
            positions=[ProjectPagePosition(key=str(row.id), id=row.id) for row in rows],
            has_more=has_more,
            total_count=total_count,
        )

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

    def plan_remove_document(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectPaperRemovalPlan:
        access = require_project_permission_for_update(
            self._db,
            project_id=project_id,
            user_id=actor.id,
            permission="manage_papers",
        )
        locked_document_id = self._db.scalar(
            select(Document.id).where(Document.id == document_id).with_for_update()
        )
        if locked_document_id is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )
        association_id = self._db.scalar(
            select(ProjectPaper.id)
            .where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == document_id,
            )
            .with_for_update()
        )
        if association_id is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                kind=FailureKind.NOT_FOUND,
            )

        revision = hashlib.sha256()
        thread_count = 0
        comment_count = 0
        annotation_filters = (
            ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project_id,
            ResearchItem.target_document_id == document_id,
        )
        revision.update(b"threads")
        for thread_id, item_updated_at, thread_updated_at in self._db.execute(
            select(
                ResearchItem.id,
                ResearchItem.updated_at,
                AnnotationThread.updated_at,
            )
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .where(*annotation_filters)
            .order_by(ResearchItem.id)
            .with_for_update()
            .execution_options(yield_per=100)
        ):
            thread_count += 1
            for field in (thread_id, item_updated_at, thread_updated_at):
                encoded = str(field).encode("utf-8")
                revision.update(len(encoded).to_bytes(8, "big"))
                revision.update(encoded)

        revision.update(b"comments")
        for comment_id, creator_id, comment_updated_at in self._db.execute(
            select(
                AnnotationComment.id,
                AnnotationComment.created_by_id,
                AnnotationComment.updated_at,
            )
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationComment.thread_id,
            )
            .where(*annotation_filters)
            .order_by(AnnotationComment.id)
            .with_for_update()
            .execution_options(yield_per=100)
        ):
            comment_count += 1
            fields = (comment_id, creator_id, comment_updated_at)
            for field in fields:
                encoded = ("" if field is None else str(field)).encode("utf-8")
                revision.update(len(encoded).to_bytes(8, "big"))
                revision.update(encoded)

        project = access.project
        return ProjectPaperRemovalPlan(
            state=ProjectPaperRemovalState(
                project_id=project_id,
                document_id=document_id,
                association_id=association_id,
                annotation_thread_count=thread_count,
                annotation_comment_count=comment_count,
                annotation_revision_digest=revision.hexdigest(),
            ),
            project_title=project.title,
        )
