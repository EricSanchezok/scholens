"""Explicit column profiles for authorized ``Document`` reads.

Canonical documents also own parsed text and page maps, which can be many
megabytes.  Metadata and authorization queries must opt into the columns they
actually present instead of hydrating those producer-owned payloads.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.modules.papers.infrastructure.models import Document

DocumentColumns = tuple[InstrumentedAttribute[Any], ...]


# The exact fields consumed by ``document_response``. Keep this profile in sync
# with that presenter so adding a public metadata field fails closed instead of
# silently issuing a lazy query for a large Document column.
DOCUMENT_RESPONSE_COLUMNS: DocumentColumns = (
    Document.id,
    Document.original_filename,
    Document.mime_type,
    Document.size_bytes,
    Document.title,
    Document.authors,
    Document.abstract,
    Document.institutions,
    Document.keywords,
    Document.doi,
    Document.journal,
    Document.publisher,
    Document.publish_date,
    Document.summary,
    Document.summary_citations,
    Document.starter_questions,
    Document.processing_status,
    Document.parser_quality,
    Document.parser_warning_code,
    Document.created_at,
    Document.updated_at,
)

DOCUMENT_LIBRARY_RESPONSE_COLUMNS: DocumentColumns = (
    *DOCUMENT_RESPONSE_COLUMNS,
    Document.preview_s3_key,
)

DOCUMENT_CONFIRMATION_COLUMNS: DocumentColumns = (
    Document.id,
    Document.sha256,
    Document.title,
    Document.original_filename,
)

DOCUMENT_PUBLIC_SHARE_COLUMNS: DocumentColumns = (
    *DOCUMENT_RESPONSE_COLUMNS,
    Document.s3_object_key,
)

# Authorization-only callers inspect at most the stable identifier and display
# title. They never need canonical content or parser artifacts.
DOCUMENT_ACCESS_COLUMNS: DocumentColumns = (
    Document.id,
    Document.title,
)

# Reading-activity authorization also needs the canonical page boundary for
# snapshot validation and paper-level coverage. Keep this profile separate
# from the authorization-only default so those callers cannot accidentally
# regress to a forbidden lazy load or hydrate unrelated canonical content.
DOCUMENT_READING_ACTIVITY_COLUMNS: DocumentColumns = (
    Document.id,
    Document.page_count,
)

# Parsed-content consumers opt into their large values explicitly. These
# profiles still avoid unrelated large fields on the same Document row.
DOCUMENT_PAPER_CONTENT_COLUMNS: DocumentColumns = (
    Document.id,
    Document.original_filename,
    Document.title,
    Document.abstract,
    Document.raw_content,
    Document.s3_object_key,
    Document.parser_markdown_s3_key,
    Document.updated_at,
)

# Lossless paging retains only these fields. Download and other full-content
# consumers use ``DOCUMENT_PAPER_CONTENT_COLUMNS`` instead.
DOCUMENT_PAPER_PAGING_COLUMNS: DocumentColumns = (
    Document.id,
    Document.title,
    Document.raw_content,
    Document.updated_at,
)

DOCUMENT_PARSED_CONTENT_COLUMNS: DocumentColumns = (
    Document.id,
    Document.raw_content,
    Document.page_offset_map,
)

DOCUMENT_CHAT_CONTEXT_COLUMNS: DocumentColumns = (
    Document.id,
    Document.title,
    Document.abstract,
    Document.raw_content,
    Document.keywords,
    Document.authors,
    Document.publish_date,
)

DOCUMENT_CITATION_COLUMNS: DocumentColumns = (
    Document.id,
    Document.title,
    Document.authors,
    Document.publish_date,
    Document.journal,
    Document.publisher,
    Document.doi,
    Document.field_provenance,
)

# Cross-module Project adapters must opt into a purpose-specific profile. The
# collection path only prices incremental storage; the storage-reference path
# only dispatches an already authorized object key.
DOCUMENT_CAPACITY_COLUMNS: DocumentColumns = (
    Document.id,
    Document.size_bytes,
)

DOCUMENT_STORAGE_REFERENCE_COLUMNS: DocumentColumns = (
    Document.id,
    Document.s3_object_key,
)
