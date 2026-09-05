"""Transport-neutral contracts for model-visible tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Generic, Literal, Protocol, TypeAlias, TypeVar
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
DEFAULT_TOOL_OUTPUT_BYTES = 200 * 1024


class ToolExecutionKind(StrEnum):
    QUERY = "query"
    ASYNC_QUERY = "async_query"
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
    reader_url: str | None = None


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
    request_started_monotonic: float = field(default_factory=time.monotonic)
    response_reserve_seconds: float = 0.0

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
        if self.request_started_monotonic < 0:
            raise ValueError("tool request start must be monotonic")
        if self.response_reserve_seconds < 0:
            raise ValueError("tool response reserve must not be negative")

    def observation_deadline(self, *, wait_seconds: int) -> float:
        """Return the transport-aware deadline for observing durable work.

        Submission is never rolled back merely because this deadline has passed.
        Callers take one current snapshot and return the durable job handle.
        """

        return self.request_started_monotonic + max(
            0.0,
            float(wait_seconds) - self.response_reserve_seconds,
        )


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    payload: JsonValue
    sources: tuple[ToolSourceCandidate, ...] = ()
    artifacts: list[dict[str, JsonValue]] = field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    resource_links: tuple[ToolResourceLink, ...] = ()


ToolHandler = Callable[[CapabilitiesT, ToolExecutionContext, BaseModel], ToolOutcome]


class ToolOutcomeFinalizer(Protocol):
    """Project and validate an outcome before its surrounding UoW commits.

    A workflow that persists an outcome receipt must persist and return the
    exact value returned by this callback. The dispatcher recognizes that
    object and does not run a non-idempotent projector a second time.
    """

    def __call__(self, outcome: ToolOutcome) -> ToolOutcome: ...


WorkflowToolHandler = Callable[
    [ToolExecutionContext, BaseModel, str, ToolOutcomeFinalizer],
    Awaitable[ToolOutcome],
]
ToolOutcomeProjector = Callable[[ToolOutcome], ToolOutcome]


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
    persist_result: bool = True
    outcome_projector: ToolOutcomeProjector | None = None
    max_output_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES
    handler: ToolHandler[CapabilitiesT] | None = None
    workflow_handler: WorkflowToolHandler | None = None
    activity_subject_field: str | None = None
    allow_repeated_calls: bool = False
    replacement_tool: str | None = None

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
        if self.max_output_bytes <= 0:
            raise ValueError("tool output byte budget must be positive")
        if self.replacement_tool is not None and (
            self.replacement_tool == self.name
            or self.replacement_tool.lower() != self.replacement_tool
            or not self.replacement_tool.isidentifier()
        ):
            raise ValueError(
                "replacement tool must be a different lowercase identifier"
            )
        if self.behavior is not None:
            if self.behavior.read_only != (
                self.execution
                in {ToolExecutionKind.QUERY, ToolExecutionKind.ASYNC_QUERY}
            ):
                raise ValueError(
                    f"tool {self.name} read_only behavior conflicts with execution"
                )
            if (
                self.confirmation_policy is ToolConfirmationPolicy.REQUIRED
                and self.behavior.read_only
            ):
                raise ValueError("read-only tools cannot require confirmation")
        if self.execution in {
            ToolExecutionKind.ASYNC_QUERY,
            ToolExecutionKind.WORKFLOW,
        }:
            if self.workflow_handler is None or self.handler is not None:
                raise ValueError(
                    "async query and workflow tools require exactly one workflow handler"
                )
            return
        if self.handler is None or self.workflow_handler is not None:
            raise ValueError("query and command tools require exactly one handler")
