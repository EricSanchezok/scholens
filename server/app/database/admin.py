from app.database.admin_auth import build_admin_authentication_backend
from app.database.database import engine
from app.database.models import (
    AnnotationComment,
    AccountPlanGrant,
    AccountQuotaOverride,
    Conversation,
    ConversationResponse,
    ConversationTurn,
    DurableJob,
    AnnotationThread,
    Onboarding,
    Document,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    Subscription,
    AuthUser,
    UserProfile,
    ZoteroImportedItem,
    ZoteroOAuthPending,
)
from fastapi import FastAPI
from sqladmin import Admin, ModelView


class ReadOnlyModelView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False


class AuthUserAdmin(ReadOnlyModelView, model=AuthUser):
    name = "SanchezCloud Identity User"
    name_plural = "SanchezCloud Identity Users"
    column_list = [
        AuthUser.id,
        AuthUser.email,
        AuthUser.display_name,
        AuthUser.status,
        AuthUser.email_verified_at,
        AuthUser.created_at,
    ]
    column_searchable_list = [AuthUser.email, AuthUser.display_name]


class UserProfileAdmin(ReadOnlyModelView, model=UserProfile):
    name = "Scholens User Profile"
    name_plural = "Scholens User Profiles"
    column_list = [
        UserProfile.user_id,
        UserProfile.locale,
        UserProfile.is_admin,
        UserProfile.is_blocked,
        UserProfile.created_at,
    ]
    column_searchable_list = [UserProfile.user_id, UserProfile.locale]


class OnboardingAdmin(ReadOnlyModelView, model=Onboarding):
    column_list = [
        Onboarding.id,
        Onboarding.user_id,
    ]
    column_searchable_list = [
        Onboarding.user_id,
        Onboarding.research_fields,
        Onboarding.job_titles,
    ]


class SubscriptionAdmin(ReadOnlyModelView, model=Subscription):
    column_list = [
        Subscription.id,
        Subscription.user_id,
        Subscription.plan,
        Subscription.status,
        Subscription.created_at,
        Subscription.cancel_at_period_end,
    ]


class AccountPlanGrantAdmin(ReadOnlyModelView, model=AccountPlanGrant):
    column_list = [
        AccountPlanGrant.id,
        AccountPlanGrant.user_id,
        AccountPlanGrant.plan,
        AccountPlanGrant.granted_by_user_id,
        AccountPlanGrant.expires_at,
        AccountPlanGrant.revoked_at,
    ]
    column_searchable_list = [AccountPlanGrant.user_id, AccountPlanGrant.plan]


class AccountQuotaOverrideAdmin(ReadOnlyModelView, model=AccountQuotaOverride):
    column_list = [
        AccountQuotaOverride.id,
        AccountQuotaOverride.user_id,
        AccountQuotaOverride.resource_key,
        AccountQuotaOverride.limit_value,
        AccountQuotaOverride.expires_at,
        AccountQuotaOverride.revoked_at,
    ]
    column_searchable_list = [
        AccountQuotaOverride.user_id,
        AccountQuotaOverride.resource_key,
    ]


class ProjectAdmin(ReadOnlyModelView, model=Project):
    column_list = [
        Project.id,
        Project.title,
        Project.description,
    ]

    column_searchable_list = [Project.title]


class ProjectCollaboratorAdmin(ReadOnlyModelView, model=ProjectCollaborator):
    column_list = [
        ProjectCollaborator.id,
        "project",
        "user",
        ProjectCollaborator.can_edit_project,
        ProjectCollaborator.can_manage_papers,
        ProjectCollaborator.can_manage_collaborators,
    ]
    column_searchable_list = [
        ProjectCollaborator.project_id,
        ProjectCollaborator.user_id,
    ]
    column_details_list = [
        ProjectCollaborator.id,
        "project",
        "user",
        ProjectCollaborator.can_edit_project,
        ProjectCollaborator.can_manage_papers,
        ProjectCollaborator.can_manage_collaborators,
    ]


class ProjectPaperAdmin(ReadOnlyModelView, model=ProjectPaper):
    column_list = [
        ProjectPaper.id,
        ProjectPaper.project_id,
        ProjectPaper.document_id,
    ]
    column_searchable_list = [ProjectPaper.project_id, ProjectPaper.document_id]


class AnnotationThreadAdmin(ReadOnlyModelView, model=AnnotationThread):
    column_list = [
        AnnotationThread.research_item_id,
        AnnotationThread.quote_text,
        AnnotationThread.page_number,
        AnnotationThread.role,
    ]
    column_searchable_list = [AnnotationThread.quote_text]


class PaperAdmin(ReadOnlyModelView, model=Document):
    column_list = [Document.id, Document.title, Document.created_by_id]
    column_searchable_list = [Document.title]


class AnnotationCommentAdmin(ReadOnlyModelView, model=AnnotationComment):
    column_list = [
        AnnotationComment.id,
        AnnotationComment.thread_id,
        AnnotationComment.created_by_id,
        AnnotationComment.content,
    ]
    column_searchable_list = [AnnotationComment.content]


class ConversationAdmin(ReadOnlyModelView, model=Conversation):
    column_list = [
        Conversation.id,
        Conversation.user_id,
        Conversation.scope_type,
        Conversation.project_id,
        Conversation.document_id,
        Conversation.title,
    ]
    column_searchable_list = [Conversation.title]


class ConversationTurnAdmin(ReadOnlyModelView, model=ConversationTurn):
    column_list = [
        ConversationTurn.id,
        ConversationTurn.conversation_id,
        ConversationTurn.depth,
        ConversationTurn.branch_index,
        ConversationTurn.user_query,
        ConversationTurn.selected_response_id,
    ]
    column_searchable_list = [ConversationTurn.user_query]


class ConversationResponseAdmin(ReadOnlyModelView, model=ConversationResponse):
    column_list = [
        ConversationResponse.id,
        ConversationResponse.turn_id,
        ConversationResponse.variant_index,
        ConversationResponse.status,
    ]
    column_searchable_list = [ConversationResponse.content]


class DurableJobAdmin(ReadOnlyModelView, model=DurableJob):
    column_list = [
        DurableJob.id,
        DurableJob.operation,
        DurableJob.requested_by_id,
        DurableJob.project_id,
        DurableJob.status,
        DurableJob.created_at,
    ]
    column_searchable_list = [
        DurableJob.operation,
        DurableJob.requested_by_id,
        DurableJob.project_id,
        DurableJob.status,
    ]


class ProjectInvitationAdmin(ReadOnlyModelView, model=ProjectInvitation):
    column_list = [
        ProjectInvitation.id,
        ProjectInvitation.project_id,
        ProjectInvitation.email,
        ProjectInvitation.expires_at,
        ProjectInvitation.created_at,
    ]
    column_searchable_list = [
        ProjectInvitation.project_id,
        ProjectInvitation.email,
    ]


class ZoteroImportedItemAdmin(ReadOnlyModelView, model=ZoteroImportedItem):
    name = "Zotero Imported Item"
    name_plural = "Zotero Imported Items"
    icon = "fa-solid fa-file-import"
    column_list = [
        ZoteroImportedItem.id,
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.status,
        ZoteroImportedItem.document_id,
        ZoteroImportedItem.error_message,
        ZoteroImportedItem.last_synced_at,
    ]
    column_searchable_list = [
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.status,
        ZoteroImportedItem.document_id,
    ]
    column_sortable_list = [
        ZoteroImportedItem.status,
        ZoteroImportedItem.last_synced_at,
    ]
    column_default_sort = [(ZoteroImportedItem.last_synced_at, True)]
    column_details_list = [
        ZoteroImportedItem.id,
        ZoteroImportedItem.user_id,
        ZoteroImportedItem.zotero_item_key,
        ZoteroImportedItem.zotero_attachment_key,
        ZoteroImportedItem.import_source,
        ZoteroImportedItem.source_url,
        ZoteroImportedItem.document_id,
        ZoteroImportedItem.upload_job_id,
        ZoteroImportedItem.status,
        ZoteroImportedItem.annotations_payload,
        ZoteroImportedItem.error_message,
        ZoteroImportedItem.last_synced_at,
    ]


class ZoteroOAuthPendingAdmin(ReadOnlyModelView, model=ZoteroOAuthPending):
    name = "Zotero OAuth Pending"
    name_plural = "Zotero OAuth Pending"
    icon = "fa-solid fa-hourglass-half"
    # oauth_token_secret is intentionally omitted to avoid exposing the secret.
    column_list = [
        ZoteroOAuthPending.id,
        ZoteroOAuthPending.user_id,
        ZoteroOAuthPending.expires_at,
    ]
    column_searchable_list = [
        ZoteroOAuthPending.user_id,
    ]
    column_sortable_list = [
        ZoteroOAuthPending.expires_at,
    ]


def setup_admin(app: FastAPI) -> None:
    admin = Admin(
        app,
        engine,
        authentication_backend=build_admin_authentication_backend(),
    )

    admin.add_view(AuthUserAdmin)
    admin.add_view(UserProfileAdmin)
    admin.add_view(OnboardingAdmin)
    admin.add_view(PaperAdmin)
    admin.add_view(AnnotationThreadAdmin)
    admin.add_view(AnnotationCommentAdmin)
    admin.add_view(ConversationAdmin)
    admin.add_view(ConversationTurnAdmin)
    admin.add_view(ConversationResponseAdmin)
    admin.add_view(ProjectAdmin)
    admin.add_view(ProjectInvitationAdmin)
    admin.add_view(ProjectCollaboratorAdmin)
    admin.add_view(ProjectPaperAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(AccountPlanGrantAdmin)
    admin.add_view(AccountQuotaOverrideAdmin)
    admin.add_view(DurableJobAdmin)
    admin.add_view(ZoteroImportedItemAdmin)
    admin.add_view(ZoteroOAuthPendingAdmin)
