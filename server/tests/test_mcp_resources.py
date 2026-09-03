from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.modules.papers.application.contracts.citation import CitationData
from app.modules.papers.application.content import (
    AccessiblePaperContentPreview,
)
from app.modules.papers.application.details import PaperDetailsResourcePreview
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    DocumentResponse,
    LibraryOutputListResponse,
    LibraryPaperListPaperEntry,
    LibraryPaperListResponse,
    LibrarySummaryResponse,
)
from app.modules.papers.application.library import LibraryPaperSummaryList
from app.modules.projects.application.contracts import (
    ProjectCapabilitiesResponse,
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectListResponse,
    ProjectMembershipResponse,
    ProjectOutputListResponse,
    ProjectOwnerResponse,
    ProjectPaperListResponse,
    ProjectPermissionSet,
    ProjectResponse,
)
from app.modules.projects.application.projects import (
    ProjectResourceCatalogItem,
    ProjectResourceMemberPage,
    ProjectResourcePage,
    ProjectResourcePaperPage,
    ProjectResourcePreview,
)
from app.modules.research.application.contracts import (
    AnnotationThreadCapabilities,
    AnnotationThreadContent,
    CitationContent,
    CitationSnapshot,
    PersonalResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
    ResearchOutputCreatorSummary,
    ResearchOutputSourceSummary,
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    DocumentProcessingStatus,
    PaperStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from app.tooling import ToolCatalog, ToolProfile
from app.tooling.workspace import MCP_TOOL_PROFILE
from app.tooling.workspace_contracts import (
    AnnotationThreadPageInput,
    EmptyInput,
    ListLibraryPapersInput,
    ListJobsInput,
    ListPaperProjectsInput,
    ListProjectMembersInput,
    ListProjectPapersInput,
    ListProjectsInput,
    ListResearchOutputSummariesInput,
    PaperContentInput,
    PaperMetadataPageInput,
    ProjectInput,
    ResearchOutputPageInput,
)
from app.transport.mcp.resource_contracts import ProjectIndexResourcePayload
from app.transport.mcp.resource_loader import ScholensResourceLoader
from app.transport.mcp.server import _MCP_RESOURCE_ERROR_MAX_UTF8_BYTES
from httpx import ASGITransport, AsyncClient
from pydantic import AnyUrl, ValidationError
from tests.test_mcp_transport import (
    RecordingDispatcher,
    _actor,
    _application,
    _initialize,
)

PROJECT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PAPER_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
THREAD_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
OUTPUT_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
LIBRARY_ENTRY_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


def _catalog() -> ToolCatalog[Any]:
    return ToolCatalog(
        [],
        [ToolProfile(name=MCP_TOOL_PROFILE, tool_names=frozenset())],
    )


def _project() -> ProjectResponse:
    return ProjectResponse(
        id=PROJECT_ID,
        title="多语言 Project café 🔬",
        description="Typed resource manifest",
        owner=ProjectOwnerResponse(
            id=7,
            display_name="Researcher",
            email="researcher@example.com",
        ),
        membership=ProjectMembershipResponse(
            kind="owner",
            permissions=ProjectPermissionSet(
                edit_project=True,
                manage_papers=True,
                manage_collaborators=True,
            ),
        ),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=True,
            transfer=True,
            delete=True,
            leave=False,
        ),
        activity_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _document() -> DocumentResponse:
    return DocumentResponse(
        document_id=PAPER_ID,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        title="论文 café 🔬",
        authors=["François", "张三"],
        abstract="Unicode round trip",
        institutions=None,
        keywords=["MCP"],
        doi=None,
        journal=None,
        publisher=None,
        publish_date=NOW,
        summary=None,
        summary_citations=None,
        starter_questions=None,
        processing_status=DocumentProcessingStatus.COMPLETED,
        parser_quality="full",
        parser_warning_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _library_papers() -> LibraryPaperListResponse:
    return LibraryPaperListResponse(
        items=[
            LibraryPaperListPaperEntry(
                library_entry_id=LIBRARY_ENTRY_ID,
                user_id=7,
                status=PaperStatus.todo,
                last_accessed_at=NOW,
                metadata_overrides=DocumentMetadataOverrides(),
                is_public=False,
                preview_url=None,
                tags=[],
                document=_document(),
                created_at=NOW,
                updated_at=NOW,
            )
        ],
        total_count=1,
    )


def _citation_item() -> ResearchItemResponse:
    return ResearchItemResponse(
        id=OUTPUT_ID,
        kind=ResearchItemKind.CITATION,
        audience=PersonalResearchAudience(),
        target_document_id=PAPER_ID,
        created_by=ResearchCreatorResponse(id=7, display_name="Researcher"),
        created_at=NOW,
        updated_at=NOW,
        capabilities=ResearchItemCapabilities(edit=True, delete=True),
        citation=CitationContent(
            snapshot=CitationSnapshot(
                kind="citation",
                document_id=str(PAPER_ID),
                preferred_style="APA",
                style_display="APA 7th Edition",
                data=CitationData(document_id=str(PAPER_ID), title="论文 café 🔬"),
                method="cached",
            )
        ),
    )


def _annotation_item() -> ResearchItemResponse:
    return ResearchItemResponse(
        id=THREAD_ID,
        kind=ResearchItemKind.ANNOTATION_THREAD,
        audience=PersonalResearchAudience(),
        target_document_id=PAPER_ID,
        created_by=ResearchCreatorResponse(id=7, display_name="Researcher"),
        created_at=NOW,
        updated_at=NOW,
        capabilities=ResearchItemCapabilities(edit=True, delete=True),
        annotation_thread=AnnotationThreadContent(
            quote_text="精确引文 🔬",
            position=None,
            color=AnnotationColor.YELLOW,
            role="user",
            mode=AnnotationThreadMode.HIGHLIGHT,
            comment_count=0,
            last_activity_at=NOW,
            status=AnnotationThreadStatus.OPEN,
            resolved_by=None,
            resolved_at=None,
            capabilities=AnnotationThreadCapabilities(
                reply=True,
                recolor=True,
                resolve=True,
                reopen=False,
                delete=True,
            ),
            comments=[],
        ),
    )


def _research_summary(item: ResearchItemResponse) -> ResearchOutputSummary:
    is_annotation = item.kind is ResearchItemKind.ANNOTATION_THREAD
    return ResearchOutputSummary(
        item_id=item.id,
        kind=item.kind,
        audience=item.audience,
        target_document_id=item.target_document_id,
        title="精确引文 🔬" if is_annotation else "论文 café 🔬",
        excerpt="Bounded catalog excerpt",
        creator=ResearchOutputCreatorSummary(id=7, display_name="Researcher"),
        created_at=item.created_at,
        updated_at=item.updated_at,
        source=ResearchOutputSourceSummary(
            audience_type=ResearchAudienceType.PERSONAL,
            audience_id=None,
            title="Personal Library",
        ),
        resource_uri=(
            f"scholens://annotation-threads/{item.id}"
            if is_annotation
            else f"scholens://research-outputs/{item.id}"
        ),
    )


class ResourceProjects:
    def list(self, **_arguments: object) -> ProjectListResponse:
        raise AssertionError("Resource loading must not hydrate full Project rows")

    def get(self, **_arguments: object) -> ProjectResponse:
        raise AssertionError("Resource loading must not hydrate full Project rows")

    def resource_projects(self, **arguments: object) -> ProjectResourcePage:
        project = _project()
        for_document = arguments.get("document_id") is not None
        return ProjectResourcePage(
            items=[
                ProjectResourcePreview(
                    value=project,
                    content_truncated=False,
                )
            ],
            has_more=for_document,
            total_count=60 if for_document else 1,
        )

    def resource_catalog(
        self, **_arguments: object
    ) -> list[ProjectResourceCatalogItem]:
        project = _project()
        return [ProjectResourceCatalogItem(id=project.id, title=project.title)]

    def resource_project(self, **_arguments: object) -> ProjectResourcePreview:
        return ProjectResourcePreview(
            value=_project(),
            content_truncated=False,
        )

    def documents(self, **_arguments: object) -> ProjectPaperListResponse:
        raise AssertionError("Resource loading must not hydrate full Project papers")

    def resource_documents(self, **_arguments: object) -> ProjectResourcePaperPage:
        return ProjectResourcePaperPage(
            value=ProjectPaperListResponse(items=[], total_count=0),
            content_truncated=False,
        )

    def members(self, **_arguments: object) -> ProjectCollaboratorListResponse:
        return ProjectCollaboratorListResponse(
            items=[
                ProjectCollaboratorResponse(
                    user_id=7,
                    display_name="Researcher",
                    email="researcher@example.com",
                    is_owner=True,
                    permissions=ProjectPermissionSet(
                        edit_project=True,
                        manage_papers=True,
                        manage_collaborators=True,
                    ),
                    joined_at=NOW,
                )
            ],
            total_count=1,
        )

    def members_page(self, **arguments: object) -> ProjectCollaboratorListResponse:
        raise AssertionError("Resource loading must not hydrate full Project members")

    def resource_members(self, **arguments: object) -> ProjectResourceMemberPage:
        assert arguments["limit"] == 50
        return ProjectResourceMemberPage(
            value=self.members().model_copy(update={"total_count": 75}),
            content_truncated=True,
        )

    def outputs(self, **_arguments: object) -> ProjectOutputListResponse:
        return ProjectOutputListResponse(items=[], total_count=0)

    def projects_for_document(self, **_arguments: object) -> ProjectListResponse:
        return ProjectListResponse(items=[_project()], total_count=1)

    def projects_for_document_page(self, **arguments: object) -> ProjectListResponse:
        assert arguments["limit"] == 25
        return self.projects_for_document().model_copy(
            update={"next_cursor": "opaque-paper-project-cursor", "total_count": 60}
        )


class ResourceLibrary:
    def summary(self, **_arguments: object) -> LibrarySummaryResponse:
        return LibrarySummaryResponse(
            paper_count=1,
            ingestion_count=0,
            attention_count=0,
            output_count=1,
        )

    def list(self, **_arguments: object) -> LibraryPaperListResponse:
        raise AssertionError("Resource loading must not hydrate full Library papers")

    def list_summaries(self, **_arguments: object) -> LibraryPaperSummaryList:
        return LibraryPaperSummaryList(
            value=_library_papers(),
            content_truncated=False,
        )

    def list_outputs(self, **_arguments: object) -> LibraryOutputListResponse:
        return LibraryOutputListResponse(items=[], total_count=0)


class ResourceResearchItems:
    def get_annotation_thread(self, **_arguments: object) -> ResearchItemResponse:
        raise AssertionError("resource manifest must not hydrate an annotation thread")

    def get_item(self, **_arguments: object) -> ResearchItemResponse:
        raise AssertionError("resource manifest must not hydrate a research output")


class ResourceResearchOutputCatalog:
    def get(self, **arguments: object) -> ResearchOutputSummary:
        item_id = arguments["item_id"]
        if item_id == THREAD_ID:
            return _research_summary(_annotation_item())
        if item_id == OUTPUT_ID:
            return _research_summary(_citation_item())
        raise AssertionError(f"unexpected resource item: {item_id}")

    def list(self, **_arguments: object) -> ResearchOutputSummaryListResponse:
        return ResearchOutputSummaryListResponse(items=[], total_count=0)


class ResourcePaperContent:
    def __init__(
        self,
        *,
        raw_content: str,
    ) -> None:
        self._raw_content = raw_content
        self.preview_calls = 0
        self.maximum_requested_characters = 0

    def read_preview(self, **arguments: object) -> AccessiblePaperContentPreview:
        self.preview_calls += 1
        max_characters = int(arguments["max_characters"])
        self.maximum_requested_characters = max(
            self.maximum_requested_characters,
            max_characters,
        )
        prefix = self._raw_content[:max_characters]
        return AccessiblePaperContentPreview(
            document_id=PAPER_ID,
            revision="resource-revision",
            content=prefix,
            total_lines=len(self._raw_content.splitlines()),
            truncated=len(prefix) != len(self._raw_content),
        )

    def read_snapshot(self, **_arguments: object) -> None:
        raise AssertionError(
            "paper Resource must not hydrate the full content snapshot"
        )


class ResourcePaperDetails:
    def __init__(self, paper: DocumentResponse) -> None:
        self._paper = paper
        self.full_calls = 0
        self.preview_calls = 0

    def __call__(self, **_arguments: object) -> DocumentResponse:
        self.full_calls += 1
        raise AssertionError("paper Resource must not hydrate full metadata")

    def resource_preview(self, **_arguments: object) -> PaperDetailsResourcePreview:
        self.preview_calls += 1
        return PaperDetailsResourcePreview(
            document=self._paper.model_copy(
                update={
                    "title": self._paper.title[:512] if self._paper.title else None,
                    "authors": None,
                    "abstract": (
                        self._paper.abstract[:1_024] if self._paper.abstract else None
                    ),
                    "institutions": None,
                    "keywords": None,
                    "summary": (
                        self._paper.summary[:1_024] if self._paper.summary else None
                    ),
                    "summary_citations": None,
                    "starter_questions": None,
                }
            ),
            content_truncated=True,
        )


class ResourceCapabilities:
    projects = ResourceProjects()
    paper_library = ResourceLibrary()
    research_items = ResourceResearchItems()
    research_output_catalog = ResourceResearchOutputCatalog()

    def __init__(
        self,
        *,
        raw_content: str = "第一行\nsecond line",
        oversized_paper_metadata: bool = False,
    ) -> None:
        self.paper_content = ResourcePaperContent(raw_content=raw_content)
        self._paper = (
            _document().model_copy(update={"abstract": "界" * 70_000})
            if oversized_paper_metadata
            else _document()
        )
        self.paper_details = ResourcePaperDetails(self._paper)

    @staticmethod
    def paper_collection_access(**_arguments: object) -> None:
        return None


class ResourceExecutor:
    def __init__(
        self,
        *,
        raw_content: str = "第一行\nsecond line",
        oversized_paper_metadata: bool = False,
    ) -> None:
        self.capabilities = ResourceCapabilities(
            raw_content=raw_content,
            oversized_paper_metadata=oversized_paper_metadata,
        )

    def query(
        self,
        operation: Callable[[ResourceCapabilities], Any],
    ) -> Any:
        return operation(self.capabilities)


def _resource_application(
    executor: object,
    *,
    permissions: frozenset[WorkspacePermission] = frozenset(WorkspacePermission),
) -> Any:
    return _application(
        _catalog(),
        RecordingDispatcher(),
        permissions=permissions,
        executor=executor,
    )


def test_mcp_resource_contract_rejects_unprojected_private_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectIndexResourcePayload.model_validate(
            {
                "resource_uri": "scholens://projects",
                "continuations": [
                    {
                        "tool": "list_projects",
                        "arguments": {"limit": 25},
                        "provides": "Accessible Projects.",
                    }
                ],
                "projects": ProjectListResponse(items=[_project()], total_count=1),
                "private_storage_key": "documents/private/source.pdf",
            }
        )


async def _read_resource(
    client: AsyncClient,
    headers: dict[str, str],
    uri: str,
    request_id: str,
) -> Any:
    return await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "resources/read",
            "params": {"uri": uri},
        },
    )


@pytest.mark.asyncio
async def test_mcp_resource_discovery_bounds_historical_project_titles() -> None:
    hostile = '\x00\x01"\\🙂' * 10_000

    class HostileProjects(ResourceProjects):
        def resource_catalog(
            self, **arguments: object
        ) -> list[ProjectResourceCatalogItem]:
            assert arguments["limit"] == 25
            return [
                ProjectResourceCatalogItem(id=uuid4(), title=hostile)
                for _index in range(25)
            ]

    class HostileCapabilities(ResourceCapabilities):
        projects = HostileProjects()

    class HostileExecutor:
        capabilities = HostileCapabilities()

        def query(self, operation: Callable[[HostileCapabilities], Any]) -> Any:
            return operation(self.capabilities)

    application = _resource_application(HostileExecutor())
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "resources",
                    "method": "resources/list",
                    "params": {},
                },
            )

    body = response.json()
    assert "error" not in body
    resources = body["result"]["resources"]
    project_resources = [
        resource
        for resource in resources
        if resource["uri"].startswith("scholens://projects/")
    ]
    assert len(project_resources) == 25
    assert all(
        len(json.dumps(resource["title"], ensure_ascii=False).encode()) <= 256
        for resource in project_resources
    )
    assert len(response.content) < 50_000


@pytest.mark.asyncio
async def test_mcp_reads_every_resource_kind_as_typed_bounded_json() -> None:
    application = _resource_application(ResourceExecutor())
    uris = {
        "library": "scholens://library",
        "projects": "scholens://projects",
        "project": f"scholens://projects/{PROJECT_ID}",
        "paper": f"scholens://papers/{PAPER_ID}",
        "annotation": f"scholens://annotation-threads/{THREAD_ID}",
        "output": f"scholens://research-outputs/{OUTPUT_ID}",
    }

    payloads: dict[str, dict[str, Any]] = {}
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            for name, uri in uris.items():
                response = await _read_resource(client, headers, uri, name)
                assert response.status_code == 200
                body = response.json()
                assert "error" not in body
                content = body["result"]["contents"][0]
                assert content["mimeType"] == "application/json"
                payloads[name] = json.loads(content["text"])

    assert payloads["library"]["papers"]["items"][0]["document"]["document_id"] == str(
        PAPER_ID
    )
    assert payloads["library"]["papers"]["items"][0]["document"]["title"] == (
        "论文 café 🔬"
    )
    expected_reader_url = f"https://scholens.local/reader/{PAPER_ID}"
    assert payloads["library"]["papers"]["items"][0]["reader_url"] == (
        expected_reader_url
    )
    assert payloads["projects"]["projects"]["items"][0]["updated_at"] == (
        "2026-08-24T09:30:00Z"
    )
    assert payloads["project"]["project"]["id"] == str(PROJECT_ID)
    assert payloads["paper"]["content_preview"]["lines"] == [
        "1: 第一行",
        "2: second line",
    ]
    assert payloads["paper"]["reader_url"] == expected_reader_url
    assert payloads["annotation"]["thread"]["item_id"] == str(THREAD_ID)
    assert payloads["annotation"]["reader_url"] == expected_reader_url
    assert payloads["output"]["research_output"]["item_id"] == str(OUTPUT_ID)
    assert payloads["output"]["reader_url"] == expected_reader_url
    assert payloads["project"]["members"]["next_cursor"] is None
    assert payloads["project"]["members"]["total_count"] == 75
    assert payloads["paper"]["projects"]["next_cursor"] is None
    assert payloads["paper"]["projects"]["total_count"] == 60
    assert {
        name: [item["tool"] for item in payload["continuations"]]
        for name, payload in payloads.items()
    } == {
        "library": [
            "list_library_paper_summaries",
            "list_jobs",
            "list_research_output_summaries",
            "get_library_summary",
        ],
        "projects": ["list_projects"],
        "project": [
            "list_project_papers",
            "list_project_members",
            "list_research_output_summaries",
            "get_project",
        ],
        "paper": ["get_paper_content", "get_paper_page", "list_paper_projects"],
        "annotation": ["get_annotation_thread_page"],
        "output": ["get_research_output_page"],
    }
    input_models = {
        "list_library_paper_summaries": ListLibraryPapersInput,
        "list_jobs": ListJobsInput,
        "list_research_output_summaries": ListResearchOutputSummariesInput,
        "get_library_summary": EmptyInput,
        "list_projects": ListProjectsInput,
        "list_project_papers": ListProjectPapersInput,
        "list_project_members": ListProjectMembersInput,
        "get_project": ProjectInput,
        "get_paper_content": PaperContentInput,
        "get_paper_page": PaperMetadataPageInput,
        "list_paper_projects": ListPaperProjectsInput,
        "get_annotation_thread_page": AnnotationThreadPageInput,
        "get_research_output_page": ResearchOutputPageInput,
    }
    for payload in payloads.values():
        for continuation in payload["continuations"]:
            input_models[continuation["tool"]].model_validate(continuation["arguments"])
    assert payloads["project"]["continuations"][1]["arguments"]["limit"] == 50
    assert payloads["paper"]["continuations"][2]["arguments"]["limit"] == 25


@pytest.mark.asyncio
async def test_mcp_paper_resource_bounds_a_single_very_long_preview_line() -> None:
    application = _resource_application(ResourceExecutor(raw_content="界" * 70_000))
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                f"scholens://papers/{PAPER_ID}",
                "large-preview",
            )

    content = response.json()["result"]["contents"][0]
    payload = json.loads(content["text"])
    assert payload.get("truncated") is not True
    assert payload["content_preview"]["truncated"] is True
    assert len(content["text"].encode("utf-8")) < 40_000
    assert len(payload["content_preview"]["lines"][0].encode("utf-8")) <= 16_400


@pytest.mark.asyncio
async def test_paper_resource_uses_a_bounded_prefix_without_snapshot_hydration() -> (
    None
):
    executor = ResourceExecutor(raw_content="界" * 70_000)
    loader = ScholensResourceLoader(executor=executor)
    uri = AnyUrl(f"scholens://papers/{PAPER_ID}")

    contents = await loader.read(actor=_actor(), uri=uri)
    payload = json.loads(contents[0].content)

    assert payload["content_preview"]["truncated"] is True
    assert executor.capabilities.paper_content.preview_calls == 1
    assert executor.capabilities.paper_content.maximum_requested_characters == 16 * 1024


@pytest.mark.asyncio
async def test_paper_resource_large_content_never_requests_the_full_snapshot() -> None:
    executor = ResourceExecutor(raw_content="x" * (2 * 1024 * 1024))
    application = _resource_application(executor)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                f"scholens://papers/{PAPER_ID}",
                "hostile-paper-size",
            )

    assert "error" not in response.json()
    assert executor.capabilities.paper_content.preview_calls == 1


@pytest.mark.asyncio
async def test_mcp_resource_projects_historical_metadata_before_serializing() -> None:
    # Historical metadata can exceed current input limits. The resource must
    # stay bounded and provide exact metadata/content continuations.
    executor = ResourceExecutor(oversized_paper_metadata=True)
    application = _resource_application(executor)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                f"scholens://papers/{PAPER_ID}",
                "large-paper",
            )

    content = response.json()["result"]["contents"][0]
    payload = json.loads(content["text"])
    assert len(content["text"].encode("utf-8")) <= 200_000
    assert payload["resource_uri"] == f"scholens://papers/{PAPER_ID}"
    assert payload.get("truncated") is not True
    assert payload["content_truncated"] is True
    assert len(payload["paper"]["abstract"].encode("utf-8")) <= 512
    assert [item["tool"] for item in payload["continuations"]] == [
        "get_paper_content",
        "get_paper_page",
        "list_paper_projects",
    ]
    assert payload["continuations"][0]["arguments"] == {
        "document_id": str(PAPER_ID),
        "max_utf8_bytes": 32_768,
    }
    assert "lossless continuation" in payload["guidance"]
    assert executor.capabilities.paper_details.full_calls == 0
    assert executor.capabilities.paper_details.preview_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uri", "jsonrpc_code", "application_code"),
    [
        (
            "scholens://library?include=private",
            -32602,
            "mcp_resource_uri_invalid",
        ),
        (
            "scholens://papers/not-a-uuid",
            -32602,
            "mcp_resource_uri_invalid",
        ),
        (
            f"scholens://unknown/{PAPER_ID}",
            -32002,
            "mcp_resource_not_found",
        ),
    ],
)
async def test_mcp_resource_errors_use_bounded_actionable_jsonrpc_errors(
    uri: str,
    jsonrpc_code: int,
    application_code: str,
) -> None:
    application = _resource_application(ResourceExecutor())
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(client, headers, uri, application_code)

    error = response.json()["error"]
    assert error["code"] == jsonrpc_code
    assert error["data"]["error"]["code"] == application_code
    assert error["data"]["error"]["stage"] == "mcp_resource_read"
    assert "remediation" in error["data"]["error"]
    assert len(response.text) < 4_000
    assert "ValidationError" not in response.text


@pytest.mark.asyncio
async def test_mcp_resource_permission_error_has_a_stable_server_code() -> None:
    application = _resource_application(
        ResourceExecutor(),
        permissions=frozenset({WorkspacePermission.WRITE}),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                "scholens://library",
                "permission-denied",
            )

    error = response.json()["error"]
    assert error["code"] == -32003
    assert error["data"]["error"]["code"] == "mcp_resource_permission_denied"
    assert error["data"]["error"]["kind"] == "permission_denied"


@pytest.mark.asyncio
async def test_mcp_resource_internal_error_never_echoes_the_exception() -> None:
    private_exception_text = "private-model-repr-and-user-content"

    class ExplodingExecutor:
        def query(self, _operation: object) -> None:
            raise RuntimeError(private_exception_text)

    application = _resource_application(ExplodingExecutor())
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                "scholens://library",
                "internal-error",
            )

    error = response.json()["error"]
    assert error["code"] == -32603
    assert error["message"] == "The Scholens resource could not be read"
    assert error["data"]["error"]["code"] == "mcp_resource_read_failed"
    assert error["data"]["error"]["kind"] == "internal"
    assert "diagnostic_id" in error["data"]["error"]
    assert private_exception_text not in response.text
    assert len(response.text) < 4_000


@pytest.mark.asyncio
async def test_mcp_resource_application_error_has_a_hard_utf8_budget() -> None:
    class OversizedErrorExecutor:
        def query(self, _operation: object) -> None:
            raise AppError(
                code="oversized_resource_error_" + "x" * 20_000,
                message='\\"\x00中🙂' * 20_000,
                kind=FailureKind.INVALID_ARGUMENT,
            )

    application = _resource_application(OversizedErrorExecutor())
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await _read_resource(
                client,
                headers,
                "scholens://library",
                "oversized-error",
            )

    error = response.json()["error"]
    assert error["code"] == -32602
    assert error["data"]["error"]["code"] == "mcp_resource_error"
    assert error["data"]["error"]["stage"] == "mcp_resource_read"
    assert len(response.content) <= _MCP_RESOURCE_ERROR_MAX_UTF8_BYTES
