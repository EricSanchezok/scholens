"""Transport-neutral contracts for model-visible tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Literal, TypeAlias, TypeVar
from uuid import UUID

from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor, OperationContext
from app.shared.domain import (
    JsonValue,
    WorkspacePermission,
    normalize_workspace_permissions,
)
from pydantic import BaseModel, Field

CapabilitiesT = TypeVar("CapabilitiesT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)


class ToolExecutionKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"
    WORKFLOW = "workflow"


class ToolConfirmationPolicy(StrEnum):
    """Whether a tool must obtain a state-bound confirmation before execution."""

    NONE = "none"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolBehavior:
    """Transport-neutral behavioral hints shown to tool-capable hosts."""

    read_only: bool
    destructive: bool = False
    idempotent: bool = False
    open_world: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolResourceLink:
    """A stable Scholens resource made available by a tool result."""

    uri: str
    name: str
    description: str | None = None
    mime_type: str = "application/json"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentSourceCandidate:
    kind: Literal["document"] = "document"
    document_id: UUID
    excerpt: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    locator: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalSourceProvenance:
    """Exact locations used to derive one external source candidate."""

    url_origin: Literal["arguments", "payload"]
    url_path: tuple[str | int, ...]
    url_start: int
    url_end: int
    excerpt_path: tuple[str | int, ...] | None = None
    excerpt_start: int | None = None
    excerpt_end: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalSourceCandidate:
    kind: Literal["external"] = "external"
    url: str
    excerpt: str | None = None
    title: str | None = None
    provenance: ExternalSourceProvenance | None = None


ToolSourceCandidate: TypeAlias = DocumentSourceCandidate | ExternalSourceCandidate


class ToolStructuredResult(BaseModel, Generic[PayloadT]):
    """Typed structured payload shared by Agent and MCP result adapters."""

    result: PayloadT
    sources: list[ToolSourceCandidate] = Field(default_factory=list)
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    resource_links: list[ToolResourceLink] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    actor: Actor
    operation: OperationContext
    paper_collection: PaperCollection
    anchor_document_id: UUID | None
    invocation_id: str
    client_ip: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.invocation_id, str)
            or not self.invocation_id
            or len(self.invocation_id) > 1024
        ):
            raise ValueError("tool invocation_id must be a bounded non-empty string")
        if (
            not isinstance(self.client_ip, str)
            or not self.client_ip
            or self.client_ip != self.client_ip.strip()
            or len(self.client_ip) > 64
        ):
            raise ValueError("tool client_ip must be a bounded normalized string")


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    payload: JsonValue
    sources: tuple[ToolSourceCandidate, ...] = ()
    artifacts: list[dict[str, JsonValue]] = field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    resource_links: tuple[ToolResourceLink, ...] = ()


ToolHandler = Callable[[CapabilitiesT, ToolExecutionContext, BaseModel], ToolOutcome]
WorkflowToolHandler = Callable[
    [ToolExecutionContext, BaseModel, str],
    Awaitable[ToolOutcome],
]


@dataclass(frozen=True, slots=True)
class ToolAccess:
    profile_name: str
    permissions: frozenset[WorkspacePermission]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permissions",
            normalize_workspace_permissions(self.permissions),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDefinition(Generic[CapabilitiesT]):
    name: str
    description: str
    input_model: type[BaseModel]
    execution: ToolExecutionKind
    required_permission: WorkspacePermission
    title: str | None = None
    output_model: type[BaseModel] | None = None
    behavior: ToolBehavior | None = None
    confirmation_policy: ToolConfirmationPolicy = ToolConfirmationPolicy.NONE
    handler: ToolHandler[CapabilitiesT] | None = None
    workflow_handler: WorkflowToolHandler | None = None
    activity_subject_field: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name.lower() != self.name
            or not self.name.isidentifier()
        ):
            raise ValueError("tool names must be non-empty lowercase identifiers")
        if self.activity_subject_field is not None:
            properties = self.input_model.model_json_schema().get("properties", {})
            if self.activity_subject_field not in properties:
                raise ValueError(
                    f"tool {self.name} activity subject field is not in its schema"
                )
        if self.required_permission is None:
            raise ValueError("business tools require one workspace permission")
        if self.behavior is not None:
            if self.behavior.read_only != (self.execution is ToolExecutionKind.QUERY):
                raise ValueError(
                    f"tool {self.name} read_only behavior conflicts with execution"
                )
            if (
                self.confirmation_policy is ToolConfirmationPolicy.REQUIRED
                and self.behavior.read_only
            ):
                raise ValueError("read-only tools cannot require confirmation")
        if self.execution is ToolExecutionKind.WORKFLOW:
            if self.workflow_handler is None or self.handler is not None:
                raise ValueError("workflow tools require exactly one workflow handler")
            return
        if self.handler is None or self.workflow_handler is not None:
            raise ValueError("query and command tools require exactly one handler")
