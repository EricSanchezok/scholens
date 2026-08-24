from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import (
    WORKSPACE_PERMISSION_ORDER,
    AppError,
    FailureKind,
    JsonValue,
    WorkspacePermission,
)
from app.tooling import (
    DocumentSourceCandidate,
    ToolAccess,
    ToolBehavior,
    ToolExecutionContext,
    ToolCatalog,
    ToolConfirmationPolicy,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolOutcomeFinalizer,
    ToolProfile,
    serialize_tool_success,
)
from app.tooling.contracts import DEFAULT_TOOL_OUTPUT_BYTES
from app.tooling.invocations import ToolInvocationGateway
from app.tooling.results import persisted_tool_outcome, restore_tool_outcome
from app.tooling.workspace import (
    CONVERSATION_TOOL_PROFILE,
    MCP_TOOL_PROFILE,
    build_workspace_tool_catalog,
)
from pydantic import BaseModel, Field

ResultT = TypeVar("ResultT")


class Arguments(BaseModel):
    value: str


class MemoryInvocationGateway(ToolInvocationGateway):
    def __init__(self) -> None:
        self.items: dict[tuple[int, str], tuple[str, str, JsonValue]] = {}
        self.operation_ids: dict[tuple[int, str], UUID] = {}

    def replay(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
    ) -> JsonValue | None:
        stored = self.items.get((actor_id, invocation_key))
        if stored is None:
            return None
        stored_name, stored_hash, result = stored
        if stored_name != tool_name or stored_hash != arguments_hash:
            raise AppError(
                code="tool_invocation_conflict",
                message="conflict",
                kind=FailureKind.CONFLICT,
            )
        return result

    def complete(
        self,
        *,
        actor_id: int,
        operation_id: UUID,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None:
        self.items[(actor_id, invocation_key)] = (
            tool_name,
            arguments_hash,
            result,
        )
        self.operation_ids[(actor_id, invocation_key)] = operation_id


@dataclass
class Capabilities:
    tool_invocations: MemoryInvocationGateway
    writes: int = 0


class Executor:
    def __init__(self, capabilities: Capabilities) -> None:
        self.capabilities = capabilities
        self.queries = 0
        self.commands = 0

    def query(self, operation: Callable[[Capabilities], ResultT]) -> ResultT:
        self.queries += 1
        return operation(self.capabilities)

    def command(self, operation: Callable[[Capabilities], ResultT]) -> ResultT:
        self.commands += 1
        return operation(self.capabilities)

    async def command_async(
        self,
        operation: Callable[[Capabilities], ResultT],
    ) -> ResultT:
        return operation(self.capabilities)


def _context() -> ToolExecutionContext:
    operation_factory = OperationContextFactory()
    request_operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=uuid4(),
            turn_id=uuid4(),
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=Actor(
            id=1,
            email="user@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation_factory.child(
            request_operation,
            initiated_by=OperationInitiator.AGENT,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="turn-1",
        client_ip="test",
    )


def _access(
    profile_name: str = "conversation",
    *permissions: WorkspacePermission,
) -> ToolAccess:
    return ToolAccess(
        profile_name=profile_name,
        permissions=frozenset(permissions or WORKSPACE_PERMISSION_ORDER),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invocation_id", ""),
        ("invocation_id", "x" * 1025),
        ("client_ip", ""),
        ("client_ip", " 127.0.0.1 "),
        ("client_ip", "x" * 65),
    ],
)
def test_tool_execution_context_rejects_unbounded_ephemeral_values(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError):
        replace(_context(), **{field: value})


def test_profiles_are_independent_and_validate_references() -> None:
    query = ToolDefinition[Capabilities](
        name="query_tool",
        description="query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=lambda capabilities, context, arguments: ToolOutcome(
            payload={"value": arguments.value}
        ),
    )
    catalog = ToolCatalog(
        [query],
        [
            ToolProfile(name="conversation", tool_names=frozenset()),
            ToolProfile(name="mcp", tool_names=frozenset({"query_tool"})),
        ],
    )

    assert catalog.definitions_for(_access("conversation")) == []
    assert [item.name for item in catalog.definitions_for(_access("mcp"))] == [
        "query_tool"
    ]
    with pytest.raises(ValueError, match="missing tools"):
        ToolCatalog(
            [query],
            [ToolProfile(name="broken", tool_names=frozenset({"missing"}))],
        )


def test_agent_metadata_requires_descriptions_on_nested_input_fields() -> None:
    class NestedInput(BaseModel):
        undocumented: str

    class RootInput(BaseModel):
        nested: NestedInput = Field(description="Nested input boundary.")

    with pytest.raises(ValueError, match=r"\$defs\.NestedInput\.undocumented"):
        ToolCatalog(
            [
                ToolDefinition[Capabilities](
                    name="nested_tool",
                    title="Nested tool",
                    description="Exercise nested schema validation.",
                    input_model=RootInput,
                    output_model=Arguments,
                    behavior=ToolBehavior(read_only=True, idempotent=True),
                    execution=ToolExecutionKind.QUERY,
                    required_permission=WorkspacePermission.READ,
                    handler=lambda capabilities, context, arguments: ToolOutcome(
                        payload={"value": "ok"}
                    ),
                )
            ],
            [ToolProfile(name="mcp", tool_names=frozenset({"nested_tool"}))],
            require_agent_metadata=True,
        )


@pytest.mark.asyncio
async def test_dispatcher_maps_unknown_tools_and_invalid_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters: list[dict[str, str]] = []
    monkeypatch.setattr(
        "app.tooling.dispatcher.add_counter",
        lambda _name, **kwargs: counters.append(kwargs["attributes"]),
    )
    definition = ToolDefinition[Capabilities](
        name="query_tool",
        description="query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=lambda capabilities, context, arguments: ToolOutcome(
            payload={"value": arguments.value}
        ),
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"query_tool"}))],
        ),
        executor=Executor(capabilities),
    )

    with pytest.raises(AppError) as unknown:
        await dispatcher.dispatch(
            name="missing",
            raw_arguments={},
            context=_context(),
            access=_access(),
        )
    assert unknown.value.code == "tool_not_found"

    with pytest.raises(AppError) as invalid:
        await dispatcher.dispatch(
            name="query_tool",
            raw_arguments={},
            context=_context(),
            access=_access(),
        )
    assert invalid.value.code == "tool_arguments_invalid"
    assert invalid.value.kind is FailureKind.INVALID_ARGUMENT
    assert [counter["error_code"] for counter in counters] == [
        "tool_not_found",
        "tool_arguments_invalid",
    ]


@pytest.mark.asyncio
async def test_async_query_dispatches_without_invocation_persistence() -> None:
    calls: list[tuple[str, str]] = []

    async def wait_query(
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del finalize_outcome
        parsed = Arguments.model_validate(arguments)
        calls.append((parsed.value, invocation_key))
        return ToolOutcome(payload={"value": parsed.value})

    definition = ToolDefinition[Capabilities](
        name="wait_query",
        description="wait",
        input_model=Arguments,
        execution=ToolExecutionKind.ASYNC_QUERY,
        required_permission=WorkspacePermission.READ,
        behavior=ToolBehavior(read_only=True, idempotent=True),
        workflow_handler=wait_query,
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    executor = Executor(capabilities)
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"wait_query"}))],
        ),
        executor=executor,
    )

    result = await dispatcher.dispatch(
        name="wait_query",
        raw_arguments={"value": "same"},
        context=_context(),
        access=_access(),
    )

    assert result.payload == {"value": "same"}
    assert calls == [("same", "turn-1:wait_query")]
    assert executor.queries == 0
    assert executor.commands == 0
    assert capabilities.tool_invocations.items == {}


@pytest.mark.asyncio
async def test_workflow_finalizer_projects_once_before_atomic_receipt() -> None:
    capabilities = Capabilities(MemoryInvocationGateway())
    executor = Executor(capabilities)
    projector_calls: list[str] = []

    def projector(outcome: ToolOutcome) -> ToolOutcome:
        parsed = Arguments.model_validate(outcome.payload)
        projector_calls.append(parsed.value)
        return replace(outcome, payload={"value": f"{parsed.value}-projected"})

    async def workflow(
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        parsed = Arguments.model_validate(arguments)

        def transact(current: Capabilities) -> ToolOutcome:
            current.writes += 1
            outcome = finalize_outcome(ToolOutcome(payload={"value": parsed.value}))
            current.tool_invocations.complete(
                actor_id=context.actor.id,
                operation_id=context.operation.trace.operation_id,
                invocation_key=invocation_key,
                tool_name="atomic_workflow",
                arguments_hash="test-hash",
                result=persisted_tool_outcome(outcome),
            )
            return outcome

        return executor.command(transact)

    definition = ToolDefinition[Capabilities](
        name="atomic_workflow",
        description="atomic workflow",
        input_model=Arguments,
        output_model=Arguments,
        execution=ToolExecutionKind.WORKFLOW,
        required_permission=WorkspacePermission.WRITE,
        persist_result=False,
        outcome_projector=projector,
        workflow_handler=workflow,
    )
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation",
                    tool_names=frozenset({"atomic_workflow"}),
                )
            ],
        ),
        executor=executor,
    )
    context = _context()

    outcome = await dispatcher.dispatch(
        name="atomic_workflow",
        raw_arguments={"value": "raw"},
        context=context,
        access=_access(),
    )

    assert outcome.payload == {"value": "raw-projected"}
    assert projector_calls == ["raw"]
    assert capabilities.writes == 1
    stored = capabilities.tool_invocations.items[
        (context.actor.id, f"{context.invocation_id}:atomic_workflow")
    ][2]
    assert isinstance(stored, dict)
    assert stored["payload"] == {"value": "raw-projected"}


@pytest.mark.asyncio
async def test_command_dispatch_is_persistently_replayed() -> None:
    def write(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context
        parsed = Arguments.model_validate(arguments)
        capabilities.writes += 1
        return ToolOutcome(
            payload={"value": parsed.value},
            sources=(
                DocumentSourceCandidate(
                    document_id=uuid4(),
                    excerpt="evidence",
                ),
            ),
            artifacts=[{"kind": "artifact"}],
            action={"kind": "write"},
        )

    definition = ToolDefinition[Capabilities](
        name="write_tool",
        description="write",
        input_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.WRITE,
        handler=write,
    )
    catalog = ToolCatalog(
        [definition],
        [ToolProfile(name="conversation", tool_names=frozenset({"write_tool"}))],
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    executor = Executor(capabilities)
    dispatcher = ToolDispatcher(catalog=catalog, executor=executor)
    context = _context()

    first = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )
    second = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )

    assert first.payload == {"value": "same"}
    assert second.payload == {"value": "same"}
    assert second.sources == first.sources
    assert second.artifacts == first.artifacts
    assert second.action == {"kind": "write"}
    assert capabilities.writes == 1
    assert executor.commands == 2
    assert (
        capabilities.tool_invocations.operation_ids[
            (context.actor.id, f"{context.invocation_id}:write_tool")
        ]
        == context.operation.trace.operation_id
    )

    with pytest.raises(AppError, match="tool_invocation_conflict") as conflict:
        await dispatcher.dispatch(
            name="write_tool",
            raw_arguments={"value": "different"},
            context=context,
            access=_access(),
        )
    assert conflict.value.code == "tool_invocation_conflict"
    assert capabilities.writes == 1


@pytest.mark.asyncio
async def test_outcome_projector_sanitizes_fresh_and_legacy_replayed_results() -> None:
    def write(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context
        capabilities.writes += 1
        parsed = Arguments.model_validate(arguments)
        return ToolOutcome(
            payload={"value": parsed.value, "raw_content": "fresh-secret"},
            action={"kind": "write", "result": {"secret": "fresh-secret"}},
        )

    def project(outcome: ToolOutcome) -> ToolOutcome:
        return replace(
            outcome,
            payload={"value": "safe"},
            action={"kind": "write"},
        )

    definition = ToolDefinition[Capabilities](
        name="projected_tool",
        description="projected write",
        input_model=Arguments,
        output_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.WRITE,
        outcome_projector=project,
        handler=write,
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation", tool_names=frozenset({"projected_tool"})
                )
            ],
        ),
        executor=Executor(capabilities),
    )
    context = _context()

    first = await dispatcher.dispatch(
        name="projected_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )
    ledger_key = (context.actor.id, f"{context.invocation_id}:projected_tool")
    stored_name, stored_hash, _stored_result = capabilities.tool_invocations.items[
        ledger_key
    ]
    capabilities.tool_invocations.items[ledger_key] = (
        stored_name,
        stored_hash,
        {
            "payload": {
                "value": "legacy",
                "raw_content": "legacy-secret" * 100_000,
            },
            "sources": [],
            "artifacts": [],
            "action": {
                "kind": "write",
                "result": {"secret": "legacy-secret" * 100_000},
            },
            "resource_links": [],
        },
    )
    replayed = await dispatcher.dispatch(
        name="projected_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )

    assert first.payload == {"value": "safe"}
    assert replayed.payload == {"value": "safe"}
    assert replayed.action == {"kind": "write"}
    assert (
        serialize_tool_success(replayed).call_tool_result_utf8_bytes
        <= DEFAULT_TOOL_OUTPUT_BYTES
    )
    assert capabilities.writes == 1


@pytest.mark.asyncio
async def test_dispatcher_rejects_a_result_over_its_utf8_byte_budget() -> None:
    outcome = ToolOutcome(payload={"value": "界" * 16})
    canonical_payload_bytes = len(
        json.dumps(
            {
                "result": outcome.payload,
                "sources": [],
                "artifacts": [],
                "action": None,
                "resource_links": [],
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    definition = ToolDefinition[Capabilities](
        name="bounded_tool",
        description="bounded query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        max_output_bytes=canonical_payload_bytes + 1,
        replacement_tool="bounded_tool_page",
        handler=lambda capabilities, context, arguments: outcome,
    )
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"bounded_tool"}))],
        ),
        executor=Executor(Capabilities(MemoryInvocationGateway())),
    )

    with pytest.raises(AppError) as error:
        await dispatcher.dispatch(
            name="bounded_tool",
            raw_arguments={"value": "ignored"},
            context=_context(),
            access=_access(),
        )

    assert error.value.code == "tool_result_budget_exceeded"
    assert error.value.kind is FailureKind.INTERNAL
    assert error.value.retryable is False
    assert error.value.details == {
        "tool": "bounded_tool",
        "max_output_bytes": canonical_payload_bytes + 1,
        "replacement_tool": "bounded_tool_page",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        ToolOutcome(payload={"score": float("nan")}),
        ToolOutcome(payload={}, artifacts=[{"score": float("inf")}]),
        ToolOutcome(payload={}, action={"score": float("-inf")}),
        ToolOutcome(
            payload={},
            sources=(
                DocumentSourceCandidate(
                    document_id=UUID("11111111-1111-1111-1111-111111111111"),
                    excerpt="evidence",
                    locator={"score": float("nan")},
                ),
            ),
        ),
        ToolOutcome(payload={"value": "\ud800"}),
        ToolOutcome(payload={"\udfff": "invalid key"}),
    ],
)
async def test_dispatcher_rejects_non_json_values_anywhere_in_a_success(
    outcome: ToolOutcome,
) -> None:
    definition = ToolDefinition[Capabilities](
        name="strict_result",
        description="strict result",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=lambda capabilities, context, arguments: outcome,
    )
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"strict_result"}))],
        ),
        executor=Executor(Capabilities(MemoryInvocationGateway())),
    )

    with pytest.raises(AppError) as exc_info:
        await dispatcher.dispatch(
            name="strict_result",
            raw_arguments={"value": "ignored"},
            context=_context(),
            access=_access(),
        )

    assert exc_info.value.code == "tool_result_invalid"
    assert exc_info.value.details == {"tool": "strict_result"}


@pytest.mark.asyncio
async def test_dispatcher_rejects_nonfinite_tool_arguments_before_execution() -> None:
    class NumericArguments(BaseModel):
        value: float

    executed = False

    def handle(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del capabilities, context, arguments
        nonlocal executed
        executed = True
        return ToolOutcome(payload={})

    definition = ToolDefinition[Capabilities](
        name="strict_arguments",
        description="strict arguments",
        input_model=NumericArguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=handle,
    )
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation",
                    tool_names=frozenset({"strict_arguments"}),
                )
            ],
        ),
        executor=Executor(Capabilities(MemoryInvocationGateway())),
    )

    with pytest.raises(AppError) as exc_info:
        await dispatcher.dispatch(
            name="strict_arguments",
            raw_arguments={"value": float("nan")},
            context=_context(),
            access=_access(),
        )

    assert exc_info.value.code == "tool_arguments_invalid"
    assert executed is False


@pytest.mark.asyncio
async def test_dispatcher_rejects_unpaired_surrogate_argument_before_execution() -> (
    None
):
    executed = False

    def handle(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del capabilities, context, arguments
        nonlocal executed
        executed = True
        return ToolOutcome(payload={})

    definition = ToolDefinition[Capabilities](
        name="strict_unicode_arguments",
        description="strict unicode arguments",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=handle,
    )
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation",
                    tool_names=frozenset({"strict_unicode_arguments"}),
                )
            ],
        ),
        executor=Executor(Capabilities(MemoryInvocationGateway())),
    )

    with pytest.raises(AppError) as exc_info:
        await dispatcher.dispatch(
            name="strict_unicode_arguments",
            raw_arguments={"value": "\ud800"},
            context=_context(),
            access=_access(),
        )

    assert exc_info.value.code == "tool_arguments_invalid"
    assert executed is False


@pytest.mark.asyncio
async def test_dispatcher_rejects_a_nonfinite_persisted_replay() -> None:
    def write(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context, arguments
        capabilities.writes += 1
        return ToolOutcome(payload={"value": "safe"})

    definition = ToolDefinition[Capabilities](
        name="strict_replay",
        description="strict replay",
        input_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.WRITE,
        handler=write,
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"strict_replay"}))],
        ),
        executor=Executor(capabilities),
    )
    context = _context()
    await dispatcher.dispatch(
        name="strict_replay",
        raw_arguments={"value": "same"},
        context=context,
        access=_access("conversation", WorkspacePermission.WRITE),
    )
    ledger_key = (context.actor.id, f"{context.invocation_id}:strict_replay")
    stored_name, stored_hash, _ = capabilities.tool_invocations.items[ledger_key]
    capabilities.tool_invocations.items[ledger_key] = (
        stored_name,
        stored_hash,
        {
            "payload": {"score": float("nan")},
            "sources": [],
            "artifacts": [],
            "action": None,
            "resource_links": [],
        },
    )

    with pytest.raises(AppError) as exc_info:
        await dispatcher.dispatch(
            name="strict_replay",
            raw_arguments={"value": "same"},
            context=context,
            access=_access("conversation", WorkspacePermission.WRITE),
        )

    assert exc_info.value.code == "tool_invocation_result_invalid"
    assert capabilities.writes == 1


def test_restore_rejects_a_malformed_persisted_resource_link() -> None:
    with pytest.raises(AppError) as exc_info:
        restore_tool_outcome(
            {
                "payload": {},
                "sources": [],
                "artifacts": [],
                "action": None,
                "resource_links": [{}],
            }
        )

    assert exc_info.value.code == "tool_invocation_result_invalid"
    assert exc_info.value.kind is FailureKind.DEPENDENCY_FAILURE


@pytest.mark.asyncio
async def test_confirmation_preview_is_never_written_to_the_invocation_ledger() -> None:
    class ConfirmedArguments(BaseModel):
        confirmation_token: str | None = None

    raw_token = "secret-confirmation-token-that-must-not-be-stored"
    definition = ToolDefinition[Capabilities](
        name="confirmed_tool",
        description="confirmed write",
        input_model=ConfirmedArguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.MANAGE,
        confirmation_policy=ToolConfirmationPolicy.REQUIRED,
        handler=lambda capabilities, context, arguments: ToolOutcome(
            payload={"confirmation_token": raw_token}
        ),
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation", tool_names=frozenset({"confirmed_tool"})
                )
            ],
        ),
        executor=Executor(capabilities),
    )

    outcome = await dispatcher.dispatch(
        name="confirmed_tool",
        raw_arguments={},
        context=_context(),
        access=_access(),
    )

    assert outcome.payload == {"confirmation_token": raw_token}
    assert capabilities.tool_invocations.items == {}


@pytest.mark.asyncio
async def test_transient_command_result_is_never_persisted_or_replayed() -> None:
    def transient_write(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context, arguments
        capabilities.writes += 1
        return ToolOutcome(
            payload={"signed_url": f"https://upload/{capabilities.writes}"}
        )

    definition = ToolDefinition[Capabilities](
        name="transient_tool",
        description="transient write",
        input_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.WRITE,
        persist_result=False,
        handler=transient_write,
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [
                ToolProfile(
                    name="conversation", tool_names=frozenset({"transient_tool"})
                )
            ],
        ),
        executor=Executor(capabilities),
    )
    context = _context()

    first = await dispatcher.dispatch(
        name="transient_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )
    capabilities.tool_invocations.items[
        (context.actor.id, f"{context.invocation_id}:transient_tool")
    ] = ("transient_tool", "intentionally-wrong-hash", {"signed_url": "stale"})
    second = await dispatcher.dispatch(
        name="transient_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )

    assert first.payload != second.payload
    assert capabilities.writes == 2
    assert list(capabilities.tool_invocations.items.values()) == [
        ("transient_tool", "intentionally-wrong-hash", {"signed_url": "stale"})
    ]


def test_workspace_profiles_share_one_canonical_definition_set() -> None:
    catalog = build_workspace_tool_catalog(
        ingestion=MagicMock(spec=PaperIngestionWorkflow),
        citations=MagicMock(spec=CitationWorkflow),
    )
    conversation = catalog.definitions_for(_access(CONVERSATION_TOOL_PROFILE))
    mcp = catalog.definitions_for(_access(MCP_TOOL_PROFILE))
    conversation_by_name = {tool.name: tool for tool in conversation}
    mcp_by_name = {tool.name: tool for tool in mcp}

    assert set(mcp_by_name) - set(conversation_by_name) == {"prepare_paper_upload"}
    assert set(conversation_by_name) - set(mcp_by_name) == {"wait_for_jobs"}
    assert "STOP" not in conversation_by_name
    assert "read_file" not in conversation_by_name
    assert len(conversation_by_name) == 63
    assert len(mcp_by_name) == 63
    assert mcp_by_name["resolve_paper_citation"].execution is ToolExecutionKind.WORKFLOW
    for name in set(conversation_by_name) & set(mcp_by_name):
        conversation_tool = conversation_by_name[name]
        mcp_tool = mcp_by_name[name]
        assert conversation_tool is mcp_tool
        assert (
            conversation_tool.input_model.model_json_schema()
            == mcp_tool.input_model.model_json_schema()
        )
