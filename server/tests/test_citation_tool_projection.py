from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from typing import Callable, TypeVar, cast
from uuid import UUID, uuid4

import pytest

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationResult,
    CitationStep,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, JsonValue, WorkspacePermission
from app.tooling import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    ToolAccess,
    ToolDispatcher,
    ToolExecutionContext,
    ToolOutcome,
    serialize_tool_success,
)
from app.tooling.catalog import ToolCatalog, ToolProfile
from app.tooling.citation_projection import (
    project_paper_citation,
    project_resolved_citation,
)
from app.tooling.workspace import MCP_TOOL_PROFILE, build_workspace_tool_catalog
from app.tooling.workspace_contracts import (
    PaperCitationReadOutput,
    ResolvedCitationOutput,
)

_HOSTILE = '\x00\x01"\\🙂'
_ResultT = TypeVar("_ResultT")


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _context() -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(),
        operation=operation,
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="citation-projection-test",
        client_ip="test",
    )


def _huge() -> str:
    return _HOSTILE * 50_000


def test_read_projection_bounds_hostile_json_bytes_in_real_call_tool_result() -> None:
    document_id = uuid4()
    huge = _huge()
    outcome = project_paper_citation(
        ToolOutcome(
            payload={
                "document_id": str(document_id),
                "preferred_style": huge,
                "data": CitationData(
                    document_id=str(document_id),
                    title=huge,
                    authors=[huge] * 100,
                    publish_date=huge,
                    journal=huge,
                    publisher=huge,
                    doi=huge,
                ).model_dump(mode="python"),
                "missing_fields": [huge] * 100,
                "complete": False,
                "guidance": huge,
            },
            artifacts=[{"legacy_duplicate": huge}],
            action={"legacy_duplicate": huge},
        )
    )

    payload = PaperCitationReadOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES
    assert payload.content_truncated is True
    assert len(payload.data.authors) == 20
    assert outcome.artifacts == []
    assert outcome.action is None
    assert "\ufffd" not in serialized.text_content


def test_resolution_projection_bounds_steps_and_omits_duplicate_artifact() -> None:
    document_id = uuid4()
    huge = _huge()
    steps = [
        CitationStep(
            kind="connector_tool",
            detail=huge,
            data={
                f"field-{index}-{huge}": {
                    f"nested-{nested}": [huge] * 20 for nested in range(20)
                }
                for index in range(20)
            },
        )
        for _ in range(30)
    ]
    citation = CitationResult(
        document_id=str(document_id),
        preferred_style=huge,
        style_display=huge,
        data=CitationData(
            document_id=str(document_id),
            title=huge,
            authors=[huge] * 100,
            publish_date=huge,
            journal=huge,
            publisher=huge,
            doi=huge,
        ),
        method="agentic",
        missing_fields=[huge] * 100,
        filled_fields={f"field-{index}": huge for index in range(100)},
        confidence=float("nan"),
        steps=steps,
    )
    payload = cast(dict[str, object], citation.model_dump(mode="python"))
    payload["resource_uri"] = huge

    outcome = project_resolved_citation(
        ToolOutcome(
            payload=cast(JsonValue, payload),
            artifacts=[cast(dict[str, JsonValue], citation.model_dump(mode="python"))],
        )
    )
    projected = ResolvedCitationOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES
    assert projected.content_truncated is True
    assert projected.confidence is None
    assert len(projected.steps) == 8
    assert all(step.data_truncated for step in projected.steps)
    assert len(projected.filled_fields) == 8
    assert outcome.artifacts == []
    assert "No duplicate citation artifact" in projected.guidance
    assert "\ufffd" not in serialized.text_content

    replayed = project_resolved_citation(outcome)
    assert replayed.payload == outcome.payload
    assert serialize_tool_success(replayed).call_tool_result_utf8_bytes == (
        serialized.call_tool_result_utf8_bytes
    )


class _InvocationStore:
    def __init__(self, *, fail_complete: bool = False) -> None:
        self.receipt: JsonValue | None = None
        self.fail_complete = fail_complete
        self.complete_calls = 0

    def replay(self, **_kwargs: object) -> JsonValue | None:
        return self.receipt

    def complete(self, *, result: JsonValue, **_kwargs: object) -> None:
        self.complete_calls += 1
        self.receipt = result
        if self.fail_complete:
            raise RuntimeError("receipt write failed")


class _Capabilities:
    def __init__(self, *, fail_complete: bool = False) -> None:
        self.tool_invocations = _InvocationStore(fail_complete=fail_complete)
        self.metadata_written = False


class _TransactionalExecutor:
    def __init__(self, capabilities: _Capabilities) -> None:
        self.capabilities = capabilities
        self.commits = 0
        self.rollbacks = 0

    def query(
        self,
        operation: Callable[[_Capabilities], _ResultT],
    ) -> _ResultT:
        return operation(self.capabilities)

    def command(
        self,
        operation: Callable[[_Capabilities], _ResultT],
    ) -> _ResultT:
        metadata_before = self.capabilities.metadata_written
        receipt_before = self.capabilities.tool_invocations.receipt
        try:
            result = operation(self.capabilities)
        except BaseException:
            self.capabilities.metadata_written = metadata_before
            self.capabilities.tool_invocations.receipt = receipt_before
            self.rollbacks += 1
            raise
        self.commits += 1
        return result

    async def command_async(
        self,
        operation: Callable[[_Capabilities], Awaitable[_ResultT]],
    ) -> _ResultT:
        metadata_before = self.capabilities.metadata_written
        receipt_before = self.capabilities.tool_invocations.receipt
        try:
            result = await operation(self.capabilities)
        except BaseException:
            self.capabilities.metadata_written = metadata_before
            self.capabilities.tool_invocations.receipt = receipt_before
            self.rollbacks += 1
            raise
        self.commits += 1
        return result


class _PreparedCitationWorkflow:
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.apply_calls = 0
        self.prepare_calls = 0

    def prepare(self, **_kwargs: object) -> object:
        self.prepare_calls += 1
        return object()

    def apply_prepared(
        self,
        capabilities: _Capabilities,
        **_kwargs: object,
    ) -> CitationResult:
        self.apply_calls += 1
        capabilities.metadata_written = True
        return CitationResult(
            document_id=str(self.document_id),
            preferred_style="APA",
            style_display="APA 7th Edition",
            data=CitationData(
                document_id=str(self.document_id),
                title="Bounded paper",
                authors=["Ada"],
                publish_date="2026-08-24",
                journal="Journal",
            ),
            method="agentic",
            filled_fields={"journal": "Journal"},
            steps=[CitationStep(kind="write_back", detail="Stored journal")],
        )


def _dispatcher(
    *,
    max_output_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES,
    fail_complete: bool = False,
) -> tuple[
    ToolDispatcher[_Capabilities],
    ToolAccess,
    _TransactionalExecutor,
    _PreparedCitationWorkflow,
]:
    capabilities = _Capabilities(fail_complete=fail_complete)
    executor = _TransactionalExecutor(capabilities)
    document_id = uuid4()
    workflow = _PreparedCitationWorkflow(document_id)
    source = build_workspace_tool_catalog(
        executor=cast(ApplicationExecutor[ApplicationCapabilities], executor),
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, workflow),
    )
    source_access = ToolAccess(
        profile_name=MCP_TOOL_PROFILE,
        permissions=frozenset({WorkspacePermission.WRITE}),
    )
    definition = replace(
        source.definition_for(source_access, "resolve_paper_citation"),
        max_output_bytes=max_output_bytes,
    )
    profile = ToolProfile(
        name="citation-atomic-test",
        tool_names=frozenset({definition.name}),
    )
    catalog = ToolCatalog([definition], [profile])
    access = ToolAccess(
        profile_name=profile.name,
        permissions=frozenset({WorkspacePermission.WRITE}),
    )
    dispatcher = ToolDispatcher(
        catalog=cast(ToolCatalog[_Capabilities], catalog),
        executor=cast(ApplicationExecutor[_Capabilities], executor),
    )
    return (
        dispatcher,
        access,
        executor,
        workflow,
    )


@pytest.mark.asyncio
async def test_resolution_budget_failure_rolls_back_metadata_and_receipt() -> None:
    dispatcher, access, executor, workflow = _dispatcher(max_output_bytes=1)

    with pytest.raises(AppError) as error:
        await dispatcher.dispatch(
            name="resolve_paper_citation",
            raw_arguments={
                "document_id": str(workflow.document_id),
                "style": "APA",
                "idempotency_key": "citation-budget-failure",
            },
            context=_context(),
            access=access,
        )

    assert error.value.code == "tool_result_budget_exceeded"
    assert workflow.apply_calls == 1
    assert executor.capabilities.metadata_written is False
    assert executor.capabilities.tool_invocations.receipt is None
    assert executor.commits == 0
    assert executor.rollbacks == 1


@pytest.mark.asyncio
async def test_resolution_success_commits_metadata_and_receipt_exactly_once() -> None:
    dispatcher, access, executor, workflow = _dispatcher()
    arguments: dict[str, object] = {
        "document_id": str(workflow.document_id),
        "style": "APA",
        "idempotency_key": "citation-success",
    }

    first = await dispatcher.dispatch(
        name="resolve_paper_citation",
        raw_arguments=arguments,
        context=_context(),
        access=access,
    )
    replayed = await dispatcher.dispatch(
        name="resolve_paper_citation",
        raw_arguments=arguments,
        context=_context(),
        access=access,
    )

    assert first == replayed
    assert workflow.prepare_calls == 1
    assert workflow.apply_calls == 1
    assert executor.capabilities.metadata_written is True
    assert executor.capabilities.tool_invocations.receipt is not None
    assert executor.capabilities.tool_invocations.complete_calls == 1
    assert executor.commits == 1
    assert executor.rollbacks == 0


@pytest.mark.asyncio
async def test_resolution_receipt_failure_rolls_back_metadata_write() -> None:
    dispatcher, access, executor, workflow = _dispatcher(fail_complete=True)

    with pytest.raises(RuntimeError, match="receipt write failed"):
        await dispatcher.dispatch(
            name="resolve_paper_citation",
            raw_arguments={
                "document_id": str(workflow.document_id),
                "style": "APA",
                "idempotency_key": "citation-receipt-failure",
            },
            context=_context(),
            access=access,
        )

    assert workflow.apply_calls == 1
    assert executor.capabilities.metadata_written is False
    assert executor.capabilities.tool_invocations.receipt is None
    assert executor.commits == 0
    assert executor.rollbacks == 1
