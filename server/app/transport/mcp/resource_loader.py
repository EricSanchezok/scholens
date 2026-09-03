"""Bounded, authorized payload loading for Scholens MCP Resources."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import mcp.types as mcp_types
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.projects.application.contracts import ProjectListResponse
from app.modules.research.application.catalog import ResearchOutputCatalogScope
from app.shared.application import Actor, ApplicationExecutor
from app.shared.application.json_values import normalize_json_value
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind
from app.tooling.library_paper_projection import (
    LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS,
    project_document,
)
from app.tooling.reader_links import build_reader_url, normalize_web_base_url
from app.tooling.project_summary_projection import (
    PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
    bounded_project_title,
    project_project,
    project_project_list,
    project_project_member_list,
    project_project_paper_list,
)
from app.transport.mcp.resource_contracts import (
    AnnotationThreadResourcePayload,
    LibraryPaperResourceIngestionEntry,
    LibraryPaperResourceList,
    LibraryPaperResourcePaperEntry,
    LibraryResourcePayload,
    MCP_RESOURCE_MAX_UTF8_BYTES,
    PaperContentPreview,
    PaperResourcePayload,
    ProjectIndexResourcePayload,
    ProjectPaperResourceList,
    ProjectPaperResourceSummary,
    ProjectResourcePayload,
    RESOURCE_TEMPLATE_CONTRACTS,
    ResearchOutputResourcePayload,
    ResearchOutputSummaryResource,
    ResearchOutputSummaryResourceList,
    ResourceContinuation,
    ScholensResourcePayload,
    STATIC_RESOURCE_CONTRACTS,
    TruncatedResourcePayload,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from pydantic import AnyUrl

_PAPER_PREVIEW_MAX_UTF8_BYTES = 16 * 1024
_PAPER_PREVIEW_MAX_LINES = 200


@dataclass(frozen=True, slots=True)
class ScholensResourceAddress:
    """A validated Scholens URI split into routing fields."""

    uri: str
    kind: str
    identifier: str

    @classmethod
    def parse(cls, uri: AnyUrl) -> ScholensResourceAddress:
        uri_text = str(uri)
        parsed = urlsplit(uri_text)
        if parsed.scheme != "scholens" or parsed.query or parsed.fragment:
            raise AppError(
                code="mcp_resource_uri_invalid",
                message="The Scholens resource URI is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return cls(
            uri=uri_text,
            kind=parsed.netloc,
            identifier=parsed.path.strip("/"),
        )

    def require_uuid(self) -> uuid.UUID:
        try:
            return uuid.UUID(self.identifier)
        except ValueError as exc:
            raise AppError(
                code="mcp_resource_uri_invalid",
                message="The resource URI must contain a valid UUID",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc


class ScholensResourceLoader:
    """Load typed resource manifests through the authorized capability surface."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        web_base_url: str = "https://scholens.local",
    ) -> None:
        self._executor = executor
        self._web_base_url = normalize_web_base_url(web_base_url)

    def _reader_url(
        self,
        document_id: uuid.UUID | None,
        *,
        project_id: uuid.UUID | None = None,
    ) -> str | None:
        if document_id is None:
            return None
        return build_reader_url(
            web_base_url=self._web_base_url,
            document_id=document_id,
            project_id=project_id,
        )

    async def list_resources(self, *, actor: Actor) -> list[mcp_types.Resource]:
        project_catalog = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.projects.resource_catalog(
                actor=actor,
                limit=25,
            ),
        )
        resources = [
            mcp_types.Resource(
                uri=AnyUrl(contract.uri),
                name=contract.name,
                title=contract.title,
                description=contract.description,
                mimeType=contract.mime_type,
            )
            for contract in STATIC_RESOURCE_CONTRACTS
        ]
        project_contract = next(
            contract
            for contract in RESOURCE_TEMPLATE_CONTRACTS
            if contract.name == "project"
        )
        resources.extend(
            mcp_types.Resource(
                uri=AnyUrl(f"scholens://projects/{project.id}"),
                name=f"project-{project.id}",
                title=bounded_project_title(project.title)[0],
                description=project_contract.description,
                mimeType=project_contract.mime_type,
            )
            for project in project_catalog
        )
        return resources

    @staticmethod
    def list_templates() -> list[mcp_types.ResourceTemplate]:
        return [
            mcp_types.ResourceTemplate(
                uriTemplate=contract.uri,
                name=contract.name,
                title=contract.title,
                description=contract.description,
                mimeType=contract.mime_type,
            )
            for contract in RESOURCE_TEMPLATE_CONTRACTS
        ]

    async def read(
        self,
        *,
        actor: Actor,
        uri: AnyUrl,
    ) -> list[ReadResourceContents]:
        address = ScholensResourceAddress.parse(uri)
        payload = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: self._load_payload(
                capabilities=capabilities,
                actor=actor,
                address=address,
            ),
        )
        return [
            ReadResourceContents(
                content=_serialize_resource_payload(
                    uri=address.uri,
                    value=payload,
                ),
                mime_type="application/json",
            )
        ]

    def _load_payload(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        address: ScholensResourceAddress,
    ) -> ScholensResourcePayload:
        if address.kind == "library" and not address.identifier:
            return self._load_library(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
            )
        if address.kind == "projects" and not address.identifier:
            return self._load_project_index(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
            )

        resource_id = address.require_uuid()
        if address.kind == "projects":
            return self._load_project(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
                project_id=resource_id,
            )
        if address.kind == "papers":
            return self._load_paper(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
                document_id=resource_id,
            )
        if address.kind == "annotation-threads":
            return self._load_annotation_thread(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
                thread_id=resource_id,
            )
        if address.kind == "research-outputs":
            return self._load_research_output(
                capabilities=capabilities,
                actor=actor,
                uri=address.uri,
                item_id=resource_id,
            )
        raise AppError(
            code="mcp_resource_not_found",
            message="The Scholens resource kind is not supported",
            kind=FailureKind.NOT_FOUND,
        )

    def _load_library(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
    ) -> LibraryResourcePayload:
        papers = capabilities.paper_library.list_summaries(
            actor=actor,
            limit=LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS,
        )
        paper_items = [
            (
                LibraryPaperResourcePaperEntry(
                    **item.model_dump(),
                    reader_url=self._reader_url(item.document.document_id),
                )
                if item.entry_type == "paper"
                else LibraryPaperResourceIngestionEntry(
                    **item.model_dump(),
                    reader_url=self._reader_url(
                        item.ingestion.document_id,
                        project_id=item.ingestion.project_id,
                    ),
                )
            )
            for item in papers.value.items
        ]
        paper_list = LibraryPaperResourceList(
            **papers.value.model_dump(exclude={"items"}),
            items=paper_items,
        )
        research_outputs = capabilities.research_output_catalog.list(
            actor=actor,
            scope=ResearchOutputCatalogScope.library(),
            limit=20,
        )
        research_output_list = ResearchOutputSummaryResourceList(
            **research_outputs.model_dump(exclude={"items"}),
            items=[
                ResearchOutputSummaryResource(
                    **item.model_dump(),
                    reader_url=self._reader_url(
                        item.target_document_id,
                        project_id=getattr(item.audience, "project_id", None),
                    ),
                )
                for item in research_outputs.items
            ],
        )
        return LibraryResourcePayload(
            resource_uri=uri,
            continuations=[
                ResourceContinuation(
                    tool="list_library_paper_summaries",
                    arguments={"limit": LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS},
                    provides="All durable Library-paper summaries.",
                ),
                ResourceContinuation(
                    tool="list_jobs",
                    arguments={"active": True, "limit": 20},
                    provides="Active Library ingestion Jobs.",
                ),
                ResourceContinuation(
                    tool="list_research_output_summaries",
                    arguments={
                        "scope": {"kind": "library"},
                        "limit": 20,
                    },
                    provides="All visible stored research-output summaries.",
                ),
                ResourceContinuation(
                    tool="get_library_summary",
                    provides="Current Library counters.",
                ),
            ],
            content_truncated=papers.content_truncated,
            guidance=(
                "Paper fields are bounded previews. Continue with "
                "list_library_paper_summaries, and use list_jobs for active "
                "ingestions. Use each paper's reader_url for durable browser links."
            ),
            summary=capabilities.paper_library.summary(actor=actor),
            papers=paper_list,
            research_outputs=research_output_list,
        )

    @staticmethod
    def _load_project_index(
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
    ) -> ProjectIndexResourcePayload:
        resource_page = capabilities.projects.resource_projects(
            actor=actor,
            limit=25,
        )
        projects = project_project_list(
            ProjectListResponse(
                items=[preview.value for preview in resource_page.items],
                total_count=resource_page.total_count,
            )
        )
        return ProjectIndexResourcePayload(
            resource_uri=uri,
            continuations=[
                ResourceContinuation(
                    tool="list_projects",
                    arguments={"limit": 25},
                    provides="All accessible Projects.",
                )
            ],
            content_truncated=(
                projects.content_truncated
                or resource_page.has_more
                or any(preview.content_truncated for preview in resource_page.items)
            ),
            guidance="Project descriptions and owner names are bounded previews.",
            projects=projects.value,
        )

    def _load_project(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
        project_id: uuid.UUID,
    ) -> ProjectResourcePayload:
        project_id_text = str(project_id)
        resource_project = capabilities.projects.resource_project(
            actor=actor,
            project_id=project_id,
        )
        project = project_project(resource_project.value)
        resource_papers = capabilities.projects.resource_documents(
            actor=actor,
            project_id=project_id,
            limit=PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
        )
        papers = project_project_paper_list(resource_papers.value)
        paper_list = ProjectPaperResourceList(
            **papers.value.model_dump(exclude={"items"}),
            items=[
                ProjectPaperResourceSummary(
                    **item.model_dump(),
                    reader_url=self._reader_url(
                        item.document_id,
                        project_id=project_id,
                    ),
                )
                for item in papers.value.items
            ],
        )
        resource_members = capabilities.projects.resource_members(
            actor=actor,
            project_id=project_id,
            limit=50,
        )
        members = project_project_member_list(resource_members.value)
        research_outputs = capabilities.research_output_catalog.list(
            actor=actor,
            scope=ResearchOutputCatalogScope.project(project_id),
            limit=20,
        )
        research_output_list = ResearchOutputSummaryResourceList(
            **research_outputs.model_dump(exclude={"items"}),
            items=[
                ResearchOutputSummaryResource(
                    **item.model_dump(),
                    reader_url=self._reader_url(
                        item.target_document_id,
                        project_id=project_id,
                    ),
                )
                for item in research_outputs.items
            ],
        )
        return ProjectResourcePayload(
            resource_uri=uri,
            continuations=[
                ResourceContinuation(
                    tool="list_project_papers",
                    arguments={
                        "project_id": project_id_text,
                        "limit": PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
                    },
                    provides="All papers associated with this Project.",
                ),
                ResourceContinuation(
                    tool="list_project_members",
                    arguments={"project_id": project_id_text, "limit": 50},
                    provides="All visible Project collaborators.",
                ),
                ResourceContinuation(
                    tool="list_research_output_summaries",
                    arguments={
                        "scope": {
                            "kind": "project",
                            "project_id": project_id_text,
                        },
                        "limit": 20,
                    },
                    provides="All stored outputs shared in this Project.",
                ),
                ResourceContinuation(
                    tool="get_project",
                    arguments={"project_id": project_id_text},
                    provides="Current Project metadata and capabilities.",
                ),
            ],
            content_truncated=any(
                (
                    project.content_truncated,
                    resource_project.content_truncated,
                    papers.content_truncated,
                    resource_papers.content_truncated,
                    members.content_truncated,
                    resource_members.content_truncated,
                )
            ),
            guidance=(
                "Project, paper, and collaborator fields are bounded previews; "
                "use the listed paginated tools for complete collections. Use each "
                "paper's reader_url for durable browser links."
            ),
            project=project.value,
            papers=paper_list,
            members=members.value,
            research_outputs=research_output_list,
        )

    def _load_paper(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
        document_id: uuid.UUID,
    ) -> PaperResourcePayload:
        capabilities.paper_collection_access(
            actor=actor,
            collection=LibraryPaperCollection(),
            document_id=document_id,
            anchor_document_id=None,
        )
        resource_metadata = capabilities.paper_details.resource_preview(
            actor=actor,
            document_id=document_id,
        )
        paper = project_document(resource_metadata.document)
        content_preview = capabilities.paper_content.read_preview(
            actor=actor,
            document_id=document_id,
            max_characters=_PAPER_PREVIEW_MAX_UTF8_BYTES,
        )
        raw_prefix = content_preview.content or ""
        bounded_prefix = json_bounded_prefix(
            raw_prefix,
            max_bytes=_PAPER_PREVIEW_MAX_UTF8_BYTES,
        )
        all_preview_lines = bounded_prefix.splitlines()
        preview_lines = all_preview_lines[:_PAPER_PREVIEW_MAX_LINES]
        preview_truncated = (
            content_preview.truncated
            or len(bounded_prefix) != len(raw_prefix)
            or len(all_preview_lines) > len(preview_lines)
        )
        document_id_text = str(document_id)
        resource_project_page = capabilities.projects.resource_projects(
            actor=actor,
            document_id=document_id,
            limit=25,
        )
        projects = project_project_list(
            ProjectListResponse(
                items=[preview.value for preview in resource_project_page.items],
                total_count=resource_project_page.total_count,
            )
        )
        return PaperResourcePayload(
            resource_uri=uri,
            reader_url=self._reader_url(document_id),
            continuations=[
                ResourceContinuation(
                    tool="get_paper_content",
                    arguments={
                        "document_id": document_id_text,
                        "max_utf8_bytes": 32_768,
                    },
                    provides="The complete lossless extracted text.",
                ),
                ResourceContinuation(
                    tool="get_paper_page",
                    arguments={
                        "document_id": document_id_text,
                        "max_utf8_bytes": 24_000,
                    },
                    provides="The complete canonical metadata JSON.",
                ),
                ResourceContinuation(
                    tool="list_paper_projects",
                    arguments={"document_id": document_id_text, "limit": 25},
                    provides="All accessible Projects containing this paper.",
                ),
            ],
            content_truncated=(
                resource_metadata.content_truncated
                or paper.content_truncated
                or projects.content_truncated
                or resource_project_page.has_more
                or any(
                    preview.content_truncated for preview in resource_project_page.items
                )
                or preview_truncated
            ),
            guidance=(
                "Metadata and content are bounded previews. Use get_paper_page and "
                "get_paper_content for lossless continuation; use reader_url for "
                "durable browser links."
            ),
            paper=paper.value,
            content_preview=PaperContentPreview(
                start_line=1,
                end_line=len(preview_lines),
                total_lines=content_preview.total_lines,
                lines=[
                    f"{index}: {line}"
                    for index, line in enumerate(preview_lines, start=1)
                ],
                truncated=preview_truncated,
            ),
            projects=projects.value,
        )

    def _load_annotation_thread(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
        thread_id: uuid.UUID,
    ) -> AnnotationThreadResourcePayload:
        thread = capabilities.research_output_catalog.get(
            actor=actor,
            item_id=thread_id,
        )
        if thread.kind is not ResearchItemKind.ANNOTATION_THREAD:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        return AnnotationThreadResourcePayload(
            resource_uri=uri,
            reader_url=self._reader_url(
                thread.target_document_id,
                project_id=getattr(thread.audience, "project_id", None),
            ),
            continuations=[
                ResourceContinuation(
                    tool="get_annotation_thread_page",
                    arguments={
                        "thread_id": str(thread_id),
                        "max_utf8_bytes": 24_000,
                    },
                    provides="The complete canonical annotation-thread JSON.",
                )
            ],
            content_truncated=True,
            guidance=(
                "This manifest contains a bounded quote preview without comments or "
                "position data. Continue get_annotation_thread_page for lossless JSON."
            ),
            thread=thread,
        )

    def _load_research_output(
        self,
        *,
        capabilities: ApplicationCapabilities,
        actor: Actor,
        uri: str,
        item_id: uuid.UUID,
    ) -> ResearchOutputResourcePayload:
        research_output = capabilities.research_output_catalog.get(
            actor=actor,
            item_id=item_id,
        )
        return ResearchOutputResourcePayload(
            resource_uri=uri,
            reader_url=self._reader_url(
                research_output.target_document_id,
                project_id=getattr(research_output.audience, "project_id", None),
            ),
            continuations=[
                ResourceContinuation(
                    tool="get_research_output_page",
                    arguments={
                        "item_id": str(item_id),
                        "max_utf8_bytes": 24_000,
                    },
                    provides="The complete canonical research-output JSON.",
                )
            ],
            content_truncated=True,
            guidance=(
                "This manifest contains a bounded typed preview. Continue "
                "get_research_output_page for lossless JSON."
            ),
            research_output=research_output,
        )


def _serialize_resource_payload(
    *,
    uri: str,
    value: ScholensResourcePayload,
) -> str:
    """Serialize one bounded resource without exposing private storage details."""
    normalized = normalize_json_value(value)
    text = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded = text.encode("utf-8")
    if len(encoded) <= MCP_RESOURCE_MAX_UTF8_BYTES:
        return text
    continuations = value.continuations
    truncated = TruncatedResourcePayload(
        resource_uri=uri,
        serialized_size_bytes=len(encoded),
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        continuation_tool=continuations[0].tool,
        continuations=continuations,
        guidance=(
            f"This resource exceeded the {MCP_RESOURCE_MAX_UTF8_BYTES}-byte MCP "
            "representation. Use the listed bounded tool calls and continue each "
            "cursor until its section is complete."
        ),
    )
    return json.dumps(
        truncated.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = ["ScholensResourceAddress", "ScholensResourceLoader"]
