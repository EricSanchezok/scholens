from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.modules.research.application.contracts import CitationSnapshot
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.shared.domain import (
    WorkspacePermission,
    ordered_workspace_permissions,
)
from app.shared.domain import FailureKind
from app.shared.domain.enums import ConversationScopeType
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from app.modules.conversations.application.contracts.contexts import TurnContext


class LibraryPaperContext(BaseModel):
    """All documents readable through personal or Project-based access."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["library"] = "library"


class SelectedPaperContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["selection"] = "selection"
    project_ids: list[UUID] = Field(default_factory=list, max_length=20)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("project_ids", "document_ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return sorted({str(UUID(str(item))) for item in value})


PaperContext = Annotated[
    LibraryPaperContext | SelectedPaperContext,
    Field(discriminator="kind"),
]
OrderedWorkspacePermissions = Annotated[
    list[WorkspacePermission],
    BeforeValidator(ordered_workspace_permissions),
]


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope_type: ConversationScopeType
    scope_id: UUID | None = None
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
    )
    paper_context: PaperContext | None = None
    tool_permissions: OrderedWorkspacePermissions | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationCreateRequest:
        needs_id = self.scope_type in {
            ConversationScopeType.PAPER,
            ConversationScopeType.PROJECT,
        }
        if needs_id != (self.scope_id is not None):
            raise ValueError("scope_id does not match scope_type")
        return self


class ConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=240)
    pinned: bool | None = None
    archived: bool | None = None


class ConversationMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["global", "project"]
    scope_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationMoveRequest:
        if self.scope_type == "project" and self.scope_id is None:
            raise ValueError("Project conversations require scope_id")
        if self.scope_type == "global" and self.scope_id is not None:
            raise ValueError("Global conversations cannot have scope_id")
        return self


class ConversationCapabilitiesResponse(BaseModel):
    rename: bool = True
    pin: bool = True
    move: bool
    detach: bool
    archive: bool = True
    share: bool = False
    delete: bool = True
    send: bool


class ConversationSummaryResponse(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    scope_type: ConversationScopeType
    scope_id: UUID | None
    scope_label: str | None
    scope_access: Literal["active", "lost"]
    read_only: bool
    read_only_reason: (
        Literal[
            "scope_access_lost",
            "project_deleted",
            "document_deleted",
        ]
        | None
    )
    pinned_at: datetime | None
    archived_at: datetime | None
    capabilities: ConversationCapabilitiesResponse


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    next_cursor: str | None


class ConversationListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = False
    scope_type: ConversationScopeType | None = None
    scope_id: UUID | None = None
    context_document_id: UUID | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_scope_filter(self) -> ConversationListRequest:
        if self.scope_type is None:
            if self.scope_id is not None or self.context_document_id is not None:
                raise ValueError("scope_id requires scope_type")
            return self
        needs_id = self.scope_type in {
            ConversationScopeType.PAPER,
            ConversationScopeType.PROJECT,
        }
        if needs_id != (self.scope_id is not None):
            raise ValueError("scope_id does not match scope_type")
        if (
            self.context_document_id is not None
            and self.scope_type is not ConversationScopeType.PROJECT
        ):
            raise ValueError("context_document_id requires project scope")
        return self


class ConversationDetailResponse(ConversationSummaryResponse):
    paper_context: PaperContext
    tool_permissions: OrderedWorkspacePermissions


class ConversationToolPermissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: OrderedWorkspacePermissions


class ConversationToolPermissionsResponse(BaseModel):
    permissions: OrderedWorkspacePermissions


class ConversationFailureResponse(BaseModel):
    """Safe, durable failure metadata available after reconnect or refresh."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    kind: FailureKind
    retryable: bool
    diagnostic_id: UUID | None = None
    correlation_id: UUID | None = None


class ConversationResponseVariantResponse(BaseModel):
    id: UUID
    variant_index: int
    status: Literal["running", "completed", "failed", "cancelled"]
    content: str | None
    references: ReferenceBundle | None
    artifacts: list[CitationSnapshot] | None
    trace: ConversationTrace | None
    duration_ms: int | None = Field(default=None, ge=0)
    failure: ConversationFailureResponse | None = None


class ConversationGenerationAccepted(BaseModel):
    """Receipt returned after a durable background generation is accepted."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    turn_id: UUID
    response_id: UUID
    variant_index: int = Field(ge=1)
    generation_kind: Literal["initial", "retry", "branch"]
    status: Literal["running"] = "running"


class ConversationGenerationCancellation(BaseModel):
    """Authoritative result of an idempotent explicit stop request."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    turn_id: UUID
    response_id: UUID
    status: Literal["completed", "failed", "cancelled"]


class ConversationTurnBranchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    count: int = Field(ge=1)
    previous_turn_id: UUID | None = None
    next_turn_id: UUID | None = None


class ConversationTurnResponse(BaseModel):
    id: UUID
    parent_turn_id: UUID | None
    user_query: str
    contexts: list[TurnContext]
    paper_context: PaperContext
    reasoning_level: str
    locale: Literal["en", "zh-CN"]
    time_zone: str
    depth: int = Field(ge=1)
    branch: ConversationTurnBranchResponse
    selected_response_id: UUID | None
    suggestions: list[str] | None
    responses: list[ConversationResponseVariantResponse]


class ConversationTurnsResponse(BaseModel):
    items: list[ConversationTurnResponse]
    path_revision: int = Field(ge=0)
    next_cursor: str | None = None


class ConversationBranchSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
