"""Database-side upper bounds for public paper metadata JSON."""

from __future__ import annotations

from sqlalchemy import BigInteger, Text, cast, func, literal
from sqlalchemy.sql.elements import ColumnElement

from app.modules.papers.infrastructure.models import Document

_DOCUMENT_TEXT_COLUMNS = (
    Document.original_filename,
    Document.mime_type,
    Document.title,
    Document.authors,
    Document.abstract,
    Document.institutions,
    Document.keywords,
    Document.doi,
    Document.journal,
    Document.publisher,
    Document.summary,
    Document.summary_citations,
    Document.starter_questions,
    Document.parser_quality,
    Document.parser_warning_code,
)


def utf8_octets(value: object) -> ColumnElement[int]:
    return cast(func.coalesce(func.octet_length(cast(value, Text)), 0), BigInteger)


def escaped_json_upper_bound(value: object) -> ColumnElement[int]:
    """Bound JSON string/container escaping without transferring the value."""

    return 6 * utf8_octets(value) + 64


def document_json_utf8_upper_bound() -> ColumnElement[int]:
    """Conservatively bound one serialized ``DocumentResponse``."""

    result: ColumnElement[int] = cast(literal(2_048), BigInteger)
    for column in _DOCUMENT_TEXT_COLUMNS:
        result = result + escaped_json_upper_bound(column)
    return result


__all__ = [
    "document_json_utf8_upper_bound",
    "escaped_json_upper_bound",
    "utf8_octets",
]
