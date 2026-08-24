"""One execution path for internal Agent and inbound MCP tool calls."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from time import monotonic
from typing import Generic, Protocol, TypeVar, cast

from app.shared.application import ApplicationExecutor
from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.domain import AppError, FailureKind
from app.tooling.catalog import ToolCatalog
from app.tooling.contracts import (
    ToolExecutionContext,
    ToolAccess,
    ToolExecutionKind,
    ToolHandler,
    ToolOutcome,
    ToolOutcomeFinalizer,
    ToolDefinition,
)
from app.tooling.invocations import ToolInvocationGateway, tool_arguments_hash
from app.tooling.results import (
    persisted_tool_outcome,
    restore_tool_outcome,
    serialize_tool_success,
)
from pydantic import BaseModel, ValidationError
from scholens_observability import add_counter, instrumented_span, record_histogram

CapabilitiesT = TypeVar("CapabilitiesT", bound="ToolInvocationCapabilities")


def _validate_outcome(
    definition: ToolDefinition[CapabilitiesT],
    outcome: ToolOutcome,
) -> ToolOutcome:
    if definition.output_model is None:
        return outcome
    try:
        payload = definition.output_model.model_validate(outcome.payload)
        normalized = normalize_json_value(payload)
    except (JsonNormalizationError, ValidationError) as exc:
        raise AppError(
            kind=FailureKind.INTERNAL,
            code="tool_result_invalid",
            message="The tool produced an invalid result",
            details={"tool": definition.name},
        ) from exc
    return replace(
        outcome,
        payload=normalized,
    )


def _finalize_outcome(
    definition: ToolDefinition[CapabilitiesT],
    outcome: ToolOutcome,
) -> ToolOutcome:
    if definition.outcome_projector is not None:
        try:
            outcome = definition.outcome_projector(outcome)
        except JsonNormalizationError as exc:
            raise AppError(
                kind=FailureKind.INTERNAL,
                code="tool_result_invalid",
                message="The tool produced an invalid result",
                details={"tool": definition.name},
            ) from exc
    outcome = _validate_outcome(definition, outcome)
    try:
        serialized = serialize_tool_success(outcome)
    except JsonNormalizationError as exc:
        raise AppError(
            kind=FailureKind.INTERNAL,
            code="tool_result_invalid",
            message="The tool produced an invalid result",
            details={"tool": definition.name},
        ) from exc
    result_bytes = serialized.call_tool_result_utf8_bytes
    record_histogram(
        "scholens.tool.result_bytes",
        result_bytes,
        attributes={"tool": definition.name},
    )
    if result_bytes > definition.max_output_bytes:
        add_counter(
            "scholens.tool.result_budget_exceeded",
            attributes={"tool": definition.name},
        )
        details: dict[str, object] = {
            "tool": definition.name,
            "max_output_bytes": definition.max_output_bytes,
        }
        if definition.replacement_tool is not None:
            details["replacement_tool"] = definition.replacement_tool
        raise AppError(
            kind=FailureKind.INTERNAL,
            code="tool_result_budget_exceeded",
            message="The tool result exceeded its safe output budget",
            details=details,
        )
    return serialized.outcome


class _DispatchOutcomeFinalizer(Generic[CapabilitiesT]):
    """Finalize once, including when a workflow validates inside its UoW."""

    def __init__(self, definition: ToolDefinition[CapabilitiesT]) -> None:
        self._definition = definition
        self._finalized: list[ToolOutcome] = []

    def __call__(self, outcome: ToolOutcome) -> ToolOutcome:
        finalized = _finalize_outcome(self._definition, outcome)
        self._finalized.append(finalized)
        return finalized

    def ensure(self, outcome: ToolOutcome) -> ToolOutcome:
        if any(outcome is finalized for finalized in self._finalized):
            return outcome
        return self(outcome)


class ToolInvocationCapabilities(Protocol):
    @property
    def tool_invocations(self) -> ToolInvocationGateway: ...


def _invocation_key(
    *,
    definition: ToolDefinition[CapabilitiesT],
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> str:
    semantic_key = getattr(arguments, "idempotency_key", None)
    confirmation_token = getattr(arguments, "confirmation_token", None)
    if semantic_key and (
        definition.confirmation_policy.value == "none" or confirmation_token
    ):
        digest = hashlib.sha256(str(semantic_key).encode()).hexdigest()
        return f"semantic:{definition.name}:{digest}"
    return f"{context.invocation_id}:{definition.name}"


def _should_persist_result(
    definition: ToolDefinition[CapabilitiesT], arguments: BaseModel
) -> bool:
    """Keep bearer credentials and pre-execution challenges out of replay storage."""
    if not definition.persist_result:
        return False
    return not (
        definition.confirmation_policy.value == "required"
        and getattr(arguments, "confirmation_token", None) is None
    )


class ToolDispatcher(Generic[CapabilitiesT]):
    def __init__(
        self,
        *,
        catalog: ToolCatalog[CapabilitiesT],
        executor: ApplicationExecutor[CapabilitiesT],
    ) -> None:
        self._catalog = catalog
        self._executor = executor

    async def dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        started = monotonic()
        status = "success"
        execution = "unknown"
        error_code = "none"
        try:
            return await self._dispatch(
                name=name,
                raw_arguments=raw_arguments,
                context=context,
                access=access,
            )
        except AppError as exc:
            status = "failure"
            error_code = exc.code
            raise
        except BaseException:
            status = "failure"
            error_code = "unexpected"
            raise
        finally:
            try:
                execution = self._catalog.definition_for(access, name).execution.value
            except KeyError:
                pass
            attributes = {
                "tool": name,
                "execution": execution,
                "status": status,
                "source": "local",
                "error_code": error_code,
            }
            add_counter("scholens.tool.calls", attributes=attributes)
            record_histogram(
                "scholens.tool.duration",
                (monotonic() - started) * 1000,
                attributes=attributes,
            )

    async def _dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        with instrumented_span(
            "tool.dispatch",
            attributes={"tool.name": name, "tool.source": "local"},
        ):
            return await self._dispatch_in_span(
                name=name,
                raw_arguments=raw_arguments,
                context=context,
                access=access,
            )

    async def _dispatch_in_span(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        try:
            definition = self._catalog.definition_for(access, name)
        except KeyError as exc:
            raise AppError(
                kind=FailureKind.NOT_FOUND,
                code="tool_not_found",
                message="Tool not found",
            ) from exc
        try:
            arguments = definition.input_model.model_validate(raw_arguments)
        except ValidationError as exc:
            raise AppError(
                kind=FailureKind.INVALID_ARGUMENT,
                code="tool_arguments_invalid",
                message="Tool arguments are invalid",
                details={
                    "errors": exc.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    )
                },
            ) from exc
        try:
            normalize_json_value(arguments)
        except JsonNormalizationError as exc:
            raise AppError(
                kind=FailureKind.INVALID_ARGUMENT,
                code="tool_arguments_invalid",
                message="Tool arguments are invalid",
                details={
                    "errors": [
                        {
                            "type": "strict_json_value",
                            "message": (
                                "Arguments must contain only finite, strict JSON values"
                            ),
                        }
                    ]
                },
            ) from exc
        if definition.execution is ToolExecutionKind.QUERY:
            handler = cast(ToolHandler[CapabilitiesT], definition.handler)
            outcome = await asyncio.to_thread(
                self._executor.query,
                lambda capabilities: handler(capabilities, context, arguments),
            )
            return _finalize_outcome(definition, outcome)
        if definition.execution is ToolExecutionKind.ASYNC_QUERY:
            async_query_handler = definition.workflow_handler
            assert async_query_handler is not None
            finalizer = _DispatchOutcomeFinalizer(definition)
            finalizer_callback: ToolOutcomeFinalizer = finalizer
            outcome = await async_query_handler(
                context,
                arguments,
                _invocation_key(
                    definition=definition,
                    context=context,
                    arguments=arguments,
                ),
                finalizer_callback,
            )
            return finalizer.ensure(outcome)
        if definition.execution is ToolExecutionKind.WORKFLOW:
            workflow_handler = definition.workflow_handler
            assert workflow_handler is not None
            fingerprint = tool_arguments_hash(arguments)
            invocation_key = _invocation_key(
                definition=definition,
                context=context,
                arguments=arguments,
            )
            persist_result = _should_persist_result(definition, arguments)
            replay = None
            if persist_result:
                replay = await asyncio.to_thread(
                    self._executor.query,
                    lambda capabilities: capabilities.tool_invocations.replay(
                        actor_id=context.actor.id,
                        invocation_key=invocation_key,
                        tool_name=name,
                        arguments_hash=fingerprint,
                    ),
                )
            if replay is not None:
                return _finalize_outcome(definition, restore_tool_outcome(replay))
            finalizer = _DispatchOutcomeFinalizer(definition)
            outcome = await workflow_handler(
                context,
                arguments,
                invocation_key,
                finalizer,
            )
            outcome = finalizer.ensure(outcome)
            if persist_result:
                await asyncio.to_thread(
                    self._executor.command,
                    lambda capabilities: capabilities.tool_invocations.complete(
                        actor_id=context.actor.id,
                        operation_id=context.operation.trace.operation_id,
                        invocation_key=invocation_key,
                        tool_name=name,
                        arguments_hash=fingerprint,
                        result=persisted_tool_outcome(outcome),
                    ),
                )
            return outcome

        assert definition.execution is ToolExecutionKind.COMMAND
        command_handler = cast(ToolHandler[CapabilitiesT], definition.handler)
        fingerprint = tool_arguments_hash(arguments)
        invocation_key = _invocation_key(
            definition=definition,
            context=context,
            arguments=arguments,
        )
        persist_result = _should_persist_result(definition, arguments)

        def execute(capabilities: CapabilitiesT) -> ToolOutcome:
            replay = None
            if persist_result:
                replay = capabilities.tool_invocations.replay(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    tool_name=name,
                    arguments_hash=fingerprint,
                )
            if replay is not None:
                return _finalize_outcome(definition, restore_tool_outcome(replay))
            outcome = _finalize_outcome(
                definition,
                command_handler(capabilities, context, arguments),
            )
            if persist_result:
                capabilities.tool_invocations.complete(
                    actor_id=context.actor.id,
                    operation_id=context.operation.trace.operation_id,
                    invocation_key=invocation_key,
                    tool_name=name,
                    arguments_hash=fingerprint,
                    result=persisted_tool_outcome(outcome),
                )
            return outcome

        return await asyncio.to_thread(self._executor.command, execute)
