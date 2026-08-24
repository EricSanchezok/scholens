"""Bounded MCP projections for Project and Project-paper collection tools."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.papers.application.contracts.documents import LibraryPaperTagResponse
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectListResponse,
    ProjectPaperListResponse,
    ProjectPaperSummaryResponse,
    ProjectResponse,
)
from app.modules.projects.application.summary_limits import (
    PROJECT_DESCRIPTION_JSON_BYTES,
    PROJECT_LIST_MAX_PAGE_ITEMS,
    PROJECT_PAPER_KEYWORD_JSON_BYTES,
    PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
    PROJECT_PAPER_LIST_VALUE_JSON_BYTES,
    PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
    PROJECT_PAPER_MAX_AUTHORS,
    PROJECT_PAPER_MAX_INSTITUTIONS,
    PROJECT_PAPER_MAX_KEYWORDS,
    PROJECT_PAPER_MAX_TAGS,
    PROJECT_TEXT_JSON_BYTES,
)
from app.tooling.bounded_projection import (
    bounded_optional_text,
    bounded_text,
    bounded_text_list,
)

PROJECT_DETAIL_DESCRIPTION_JSON_BYTES = 48 * 1024
PROJECT_DETAIL_TEXT_JSON_BYTES = 2 * 1024
PROJECT_MEMBER_NAME_JSON_BYTES = 128
PROJECT_MEMBER_EMAIL_JSON_BYTES = 256

PROJECT_LIST_GUIDANCE = (
    "Descriptions are bounded previews. Use get_project with a project_id for the "
    "complete Project, and continue with next_cursor when present."
)
PROJECT_PAPER_LIST_GUIDANCE = (
    "Paper metadata is a bounded preview. Use get_paper_page with a document_id for "
    "lossless complete JSON, and continue with next_cursor when present."
)
PROJECT_MEMBER_LIST_GUIDANCE = (
    "Display names are bounded and unusually large historical email values use an "
    "explicit example.com placeholder when content_truncated is true. Continue with "
    "next_cursor and use immutable user_id values for membership changes."
)


@dataclass(frozen=True, slots=True)
class ProjectListProjection:
    value: ProjectListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectProjection:
    value: ProjectResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectPaperListProjection:
    value: ProjectPaperListResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class ProjectMemberListProjection:
    value: ProjectCollaboratorListResponse
    content_truncated: bool


def bounded_project_title(value: str) -> tuple[str, bool]:
    """Project a title without coupling resource discovery to full Project DTOs."""

    return bounded_text(value, max_bytes=PROJECT_TEXT_JSON_BYTES)


def _project_member(
    value: ProjectCollaboratorResponse,
) -> tuple[ProjectCollaboratorResponse, bool]:
    display_name, display_name_truncated = bounded_text(
        value.display_name,
        max_bytes=PROJECT_MEMBER_NAME_JSON_BYTES,
    )
    _, email_truncated = bounded_text(
        str(value.email),
        max_bytes=PROJECT_MEMBER_EMAIL_JSON_BYTES,
    )
    email = (
        f"truncated-user-{value.user_id}@example.com"
        if email_truncated
        else str(value.email)
    )
    return (
        value.model_copy(update={"display_name": display_name, "email": email}),
        display_name_truncated or email_truncated,
    )


def project_project_member_list(
    value: ProjectCollaboratorListResponse,
) -> ProjectMemberListProjection:
    items: list[ProjectCollaboratorResponse] = []
    truncated = False
    for item in value.items:
        projected, item_truncated = _project_member(item)
        items.append(projected)
        truncated = truncated or item_truncated
    return ProjectMemberListProjection(
        value=value.model_copy(update={"items": items}),
        content_truncated=truncated,
    )


def project_project(value: ProjectResponse) -> ProjectProjection:
    title, title_truncated = bounded_project_title(value.title)
    description, description_truncated = bounded_optional_text(
        value.description,
        max_bytes=PROJECT_DESCRIPTION_JSON_BYTES,
    )
    owner_name, owner_truncated = bounded_text(
        value.owner.display_name,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    return ProjectProjection(
        value=value.model_copy(
            update={
                "title": title,
                "description": description,
                "owner": value.owner.model_copy(update={"display_name": owner_name}),
            }
        ),
        content_truncated=(title_truncated or description_truncated or owner_truncated),
    )


def project_project_detail(value: ProjectResponse) -> ProjectProjection:
    """Bound a single legacy Project response below the full MCP envelope cap.

    The compatibility text block causes Project strings to be JSON-escaped a
    second time. A 48 KiB description leaves deterministic headroom for the
    structured copy, action, links, owner identity, and hostile escape-heavy
    historical values while preserving every currently accepted 10k-character
    description in ordinary Unicode text.
    """

    title, title_truncated = bounded_text(
        value.title,
        max_bytes=PROJECT_DETAIL_TEXT_JSON_BYTES,
    )
    description, description_truncated = bounded_optional_text(
        value.description,
        max_bytes=PROJECT_DETAIL_DESCRIPTION_JSON_BYTES,
    )
    owner_name, owner_truncated = bounded_text(
        value.owner.display_name,
        max_bytes=PROJECT_DETAIL_TEXT_JSON_BYTES,
    )
    return ProjectProjection(
        value=value.model_copy(
            update={
                "title": title,
                "description": description,
                "owner": value.owner.model_copy(update={"display_name": owner_name}),
            }
        ),
        content_truncated=(title_truncated or description_truncated or owner_truncated),
    )


def project_project_list(value: ProjectListResponse) -> ProjectListProjection:
    items: list[ProjectResponse] = []
    truncated = False
    for item in value.items:
        projection = project_project(item)
        items.append(projection.value)
        truncated = truncated or projection.content_truncated
    return ProjectListProjection(
        value=value.model_copy(update={"items": items}),
        content_truncated=truncated,
    )


def _project_tag(
    value: LibraryPaperTagResponse,
) -> tuple[LibraryPaperTagResponse, bool]:
    name, name_truncated = bounded_text(
        value.name,
        max_bytes=PROJECT_PAPER_KEYWORD_JSON_BYTES,
    )
    color, color_truncated = bounded_optional_text(
        value.color,
        max_bytes=PROJECT_PAPER_KEYWORD_JSON_BYTES,
    )
    return (
        value.model_copy(update={"name": name, "color": color}),
        name_truncated or color_truncated,
    )


def _project_tags(
    values: list[LibraryPaperTagResponse],
) -> tuple[list[LibraryPaperTagResponse], bool]:
    projected: list[LibraryPaperTagResponse] = []
    page = values[:PROJECT_PAPER_MAX_TAGS]
    truncated = len(page) != len(values)
    for value in page:
        tag, tag_truncated = _project_tag(value)
        projected.append(tag)
        truncated = truncated or tag_truncated
    return projected, truncated


def _project_project_paper(
    value: ProjectPaperSummaryResponse,
) -> tuple[ProjectPaperSummaryResponse, bool]:
    title, title_truncated = bounded_optional_text(
        value.title,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    abstract, abstract_truncated = bounded_optional_text(
        value.abstract,
        max_bytes=PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
    )
    summary, summary_truncated = bounded_optional_text(
        value.summary,
        max_bytes=PROJECT_PAPER_LONG_TEXT_JSON_BYTES,
    )
    authors, authors_truncated = bounded_text_list(
        value.authors,
        max_items=PROJECT_PAPER_MAX_AUTHORS,
        item_max_bytes=PROJECT_PAPER_LIST_VALUE_JSON_BYTES,
    )
    institutions, institutions_truncated = bounded_text_list(
        value.institutions,
        max_items=PROJECT_PAPER_MAX_INSTITUTIONS,
        item_max_bytes=PROJECT_PAPER_LIST_VALUE_JSON_BYTES,
    )
    keywords, keywords_truncated = bounded_text_list(
        value.keywords,
        max_items=PROJECT_PAPER_MAX_KEYWORDS,
        item_max_bytes=PROJECT_PAPER_KEYWORD_JSON_BYTES,
    )
    journal, journal_truncated = bounded_optional_text(
        value.journal,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    publisher, publisher_truncated = bounded_optional_text(
        value.publisher,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    doi, doi_truncated = bounded_optional_text(
        value.doi,
        max_bytes=PROJECT_TEXT_JSON_BYTES,
    )
    tags, tags_truncated = _project_tags(value.personal_tags)
    urls_removed = value.file_url is not None or value.preview_url is not None
    return (
        value.model_copy(
            update={
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "institutions": institutions,
                "journal": journal,
                "publisher": publisher,
                "doi": doi,
                "file_url": None,
                "preview_url": None,
                "summary": summary,
                "keywords": keywords or [],
                "personal_tags": tags,
            }
        ),
        any(
            (
                title_truncated,
                abstract_truncated,
                summary_truncated,
                authors_truncated,
                institutions_truncated,
                keywords_truncated,
                journal_truncated,
                publisher_truncated,
                doi_truncated,
                tags_truncated,
                urls_removed,
            )
        ),
    )


def project_project_paper_list(
    value: ProjectPaperListResponse,
) -> ProjectPaperListProjection:
    items: list[ProjectPaperSummaryResponse] = []
    truncated = False
    for item in value.items:
        projected, item_truncated = _project_project_paper(item)
        items.append(projected)
        truncated = truncated or item_truncated
    return ProjectPaperListProjection(
        value=value.model_copy(update={"items": items}),
        content_truncated=truncated,
    )


__all__ = [
    "PROJECT_DESCRIPTION_JSON_BYTES",
    "PROJECT_DETAIL_DESCRIPTION_JSON_BYTES",
    "PROJECT_DETAIL_TEXT_JSON_BYTES",
    "PROJECT_LIST_GUIDANCE",
    "PROJECT_LIST_MAX_PAGE_ITEMS",
    "PROJECT_MEMBER_EMAIL_JSON_BYTES",
    "PROJECT_MEMBER_LIST_GUIDANCE",
    "PROJECT_MEMBER_NAME_JSON_BYTES",
    "PROJECT_PAPER_LIST_GUIDANCE",
    "PROJECT_PAPER_LIST_MAX_PAGE_ITEMS",
    "ProjectListProjection",
    "ProjectProjection",
    "ProjectMemberListProjection",
    "ProjectPaperListProjection",
    "bounded_project_title",
    "project_project_list",
    "project_project",
    "project_project_detail",
    "project_project_member_list",
    "project_project_paper_list",
]
