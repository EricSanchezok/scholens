"""Cross-domain PostgreSQL projection for canonical paper search."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import logging
import math
import re
from typing import Literal, cast
import unicodedata
from uuid import UUID

from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    try_local_embedder,
)

from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.search import (
    PaperSearchCandidate,
    PaperSearchCandidatePage,
    PaperSearchQuery,
    PaperSearchResponse,
    PaperSearchResult,
    LibraryPaperCollection,
    PersonalLibraryPaperCollection,
    SelectedPaperCollection,
    PaperSearchSnippet,
    PaperSearchSort,
    PaperSearchStats,
)
from app.modules.papers.application.contracts.documents import (
    LibraryPaperTagResponse,
)
from app.modules.papers.infrastructure.models import (
    Document,
    DocumentPassage,
    DocumentSearchEmbedding,
    LibraryPaper,
    LibraryPaperTag,
    PaperTag,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.projects.infrastructure.models import (
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.shared.application import Actor
from app.shared.application.text import json_bounded_prefix
from app.shared.infrastructure.sql_patterns import literal_contains_pattern
from app.shared.infrastructure.text_excerpt import plain_query_excerpt
from sqlalchemy import ColumnElement, and_, case, exists, false, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

logger = logging.getLogger(__name__)

RetrievalMode = Literal["exact", "full_text", "fuzzy", "semantic"]
_PASSAGE_CHARACTERS = 1_200
_CANDIDATE_TITLE_CHARACTERS = 240
_CANDIDATE_TEXT_CHARACTERS = 1_200
_CANDIDATE_TITLE_JSON_BYTES = 384
_CANDIDATE_TEXT_JSON_BYTES = 900
_TRIGRAM_SIMILARITY_MIN = 0.12
# These conservative acceptance guardrails are scoped to this exact local E5
# projection. A model revision must deliberately review them; loosening them
# requires the fixed relevance evaluation set called for by ADR 0030.
_E5_POLICY_MODEL_REVISION = "multilingual-e5-small-onnx-o4-v1"
if EMBEDDING_MODEL_REVISION != _E5_POLICY_MODEL_REVISION:
    raise RuntimeError("paper search semantic acceptance policy requires review")
_E5_SEMANTIC_MAX_COSINE_DISTANCE = 0.20
_E5_SEMANTIC_BEST_DISTANCE_DELTA = 0.04
_E5_SEMANTIC_ONLY_RESULT_LIMIT = 20
_CJK_RANGES = (
    (0x3040, 0x30FF),
    (0x31F0, 0x31FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
)


@dataclass(frozen=True, slots=True)
class _PaperSearchQueryPlan:
    normalized: str
    compact: str
    hybrid: bool
    publication_year: int | None


def _normalize_query(query: str) -> str:
    return unicodedata.normalize("NFKC", query).strip().casefold()


def _compact_query(query: str) -> str:
    normalized = _normalize_query(query)
    return "".join(character for character in normalized if character.isalnum())


def _normalize_doi(value: str) -> str:
    normalized = _normalize_query(value)
    normalized = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        normalized,
    )
    return "".join(normalized.split())


def _strict_word_pattern(query: str) -> str:
    return rf"(^|[^[:alnum:]]){re.escape(query)}([^[:alnum:]]|$)"


def _contains_complete_metadata_token(value: str, query: str) -> bool:
    normalized_value = _normalize_query(value)
    if not query:
        return False
    start = normalized_value.find(query)
    while start >= 0:
        end = start + len(query)
        left_boundary = start == 0 or not normalized_value[start - 1].isalnum()
        right_boundary = (
            end == len(normalized_value) or not normalized_value[end].isalnum()
        )
        if left_boundary and right_boundary:
            return True
        start = normalized_value.find(query, start + 1)
    return False


def _query_plan(query: str) -> _PaperSearchQueryPlan:
    normalized = _normalize_query(query)
    compact = _compact_query(normalized)
    numeric_only = normalized.isdecimal()
    cjk_count = sum(
        any(start <= ord(character) <= end for start, end in _CJK_RANGES)
        for character in normalized
    )
    return _PaperSearchQueryPlan(
        normalized=normalized,
        compact=compact,
        hybrid=not numeric_only and (len(compact) >= 3 or cjk_count >= 2),
        publication_year=(
            int(normalized) if numeric_only and len(normalized) == 4 else None
        ),
    )


def _metadata_exact_condition(
    plan: _PaperSearchQueryPlan,
) -> ColumnElement[bool]:
    if not plan.normalized:
        return false()
    normalized_doi = func.regexp_replace(
        func.regexp_replace(
            func.lower(func.btrim(func.coalesce(Document.doi, ""))),
            r"^(https?://(dx\.)?doi\.org/|doi:[[:space:]]*)",
            "",
            "i",
        ),
        r"[[:space:]]+",
        "",
        "g",
    )
    normalized_query_doi = _normalize_doi(plan.normalized)
    conditions: list[ColumnElement[bool]] = (
        [normalized_doi == normalized_query_doi] if normalized_query_doi else []
    )
    if plan.hybrid:
        pattern = literal_contains_pattern(plan.normalized)
        compact_title = func.regexp_replace(
            func.lower(func.coalesce(Document.title, "")),
            "[^[:alnum:]]",
            "",
            "g",
        )
        conditions.extend(
            [
                func.lower(func.coalesce(Document.title, "")).like(
                    pattern, escape="\\"
                ),
                and_(
                    Document.search_text_compact.contains(plan.compact),
                    compact_title.contains(plan.compact),
                ),
                func.lower(
                    func.coalesce(func.array_to_string(Document.authors, " "), "")
                ).like(pattern, escape="\\"),
                func.lower(
                    func.coalesce(func.array_to_string(Document.keywords, " "), "")
                ).like(pattern, escape="\\"),
            ]
        )
    else:
        word_pattern = _strict_word_pattern(plan.normalized)
        conditions.extend(
            [
                func.coalesce(Document.title, "").op("~*")(word_pattern),
                func.coalesce(func.array_to_string(Document.authors, " "), "").op("~*")(
                    word_pattern
                ),
                func.coalesce(func.array_to_string(Document.keywords, " "), "").op(
                    "~*"
                )(word_pattern),
            ]
        )
    if plan.publication_year is not None:
        conditions.append(
            func.extract("year", Document.publish_date) == plan.publication_year
        )
    return or_(*conditions)


def _accepted_semantic_candidates(
    candidates: list[tuple[UUID, float]],
    *,
    lexical_ids: set[UUID],
    has_exact_metadata: bool,
) -> list[UUID]:
    """Apply conservative E5 acceptance guardrails without dropping lexical hits."""

    finite_candidates = [
        (document_id, distance)
        for document_id, distance in candidates
        if math.isfinite(distance)
    ]
    if not finite_candidates:
        return []
    best_distance = min(distance for _document_id, distance in finite_candidates)
    accepted: list[UUID] = []
    accepted_set: set[UUID] = set()
    semantic_only_count = 0
    for document_id, distance in finite_candidates:
        if document_id in accepted_set:
            continue
        if document_id in lexical_ids:
            accepted.append(document_id)
            accepted_set.add(document_id)
            continue
        if has_exact_metadata:
            continue
        if semantic_only_count >= _E5_SEMANTIC_ONLY_RESULT_LIMIT:
            continue
        if (
            distance <= _E5_SEMANTIC_MAX_COSINE_DISTANCE
            and distance <= best_distance + _E5_SEMANTIC_BEST_DISTANCE_DELTA
        ):
            accepted.append(document_id)
            accepted_set.add(document_id)
            semantic_only_count += 1
    return accepted


@dataclass(frozen=True, slots=True)
class _SearchRanking:
    conditions: list[ColumnElement[bool]]
    text_query: object
    retrieval_modes: dict[UUID, set[RetrievalMode]]
    semantic_ids: list[UUID]
    ranked_ids: list[UUID]


def _visibility_condition(
    *,
    actor: Actor,
    collection: (
        LibraryPaperCollection
        | PersonalLibraryPaperCollection
        | SelectedPaperCollection
    ),
) -> ColumnElement[bool]:
    if isinstance(collection, LibraryPaperCollection):
        return accessible_document_condition(user_id=actor.id)
    if isinstance(collection, PersonalLibraryPaperCollection):
        return exists(
            select(LibraryPaper.document_id).where(
                LibraryPaper.document_id == Document.id,
                LibraryPaper.user_id == actor.id,
            )
        )
    conditions: list[ColumnElement[bool]] = []
    if collection.document_ids:
        conditions.append(Document.id.in_(collection.document_ids))
    if collection.project_ids:
        in_projects = exists(
            select(ProjectPaper.document_id)
            .join(Project, Project.id == ProjectPaper.project_id)
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == actor.id,
                ),
            )
            .where(
                ProjectPaper.document_id == Document.id,
                ProjectPaper.project_id.in_(collection.project_ids),
                or_(
                    Project.owner_id == actor.id,
                    ProjectCollaborator.user_id == actor.id,
                ),
            )
        )
        conditions.append(in_projects)
    return or_(*conditions)


def _matching_fields(
    document: Document,
    plan: _PaperSearchQueryPlan,
    *,
    has_passage: bool,
) -> list[str]:
    fields: list[str] = []
    candidates = (
        ("title", document.title),
        ("authors", " ".join(document.authors or [])),
        ("keywords", " ".join(document.keywords or [])),
        ("abstract", document.abstract),
        ("doi", document.doi),
    )
    for name, value in candidates:
        normalized_value = _normalize_query(value or "")
        if plan.hybrid:
            literal_match = bool(
                plan.normalized and plan.normalized in normalized_value
            )
            compact_match = name == "title" and bool(
                plan.compact and plan.compact in _compact_query(normalized_value)
            )
            matches = literal_match or compact_match
        elif name in {"title", "authors", "keywords"}:
            matches = _contains_complete_metadata_token(
                normalized_value,
                plan.normalized,
            )
        elif name == "doi":
            matches = _normalize_doi(normalized_value) == _normalize_doi(
                plan.normalized
            )
        else:
            matches = False
        if matches:
            fields.append(name)
    if (
        plan.publication_year is not None
        and document.publish_date is not None
        and document.publish_date.year == plan.publication_year
    ):
        fields.append("publish_date")
    if has_passage:
        fields.append("body")
    return fields


def _matching_passages(
    db: Session,
    *,
    document_ids: list[UUID],
    text_query: object,
    query: str,
) -> dict[UUID, list[PaperSearchSnippet]]:
    if not document_ids:
        return {}
    passage_rank = func.ts_rank_cd(DocumentPassage.ts_vector, text_query)
    ranked = (
        select(
            DocumentPassage.document_id.label("document_id"),
            DocumentPassage.start_line.label("start_line"),
            DocumentPassage.end_line.label("end_line"),
            func.left(DocumentPassage.content, _PASSAGE_CHARACTERS).label("content"),
            func.row_number()
            .over(
                partition_by=DocumentPassage.document_id,
                order_by=(passage_rank.desc(), DocumentPassage.start_line),
            )
            .label("position"),
        )
        .where(
            DocumentPassage.document_id.in_(document_ids),
            DocumentPassage.ts_vector.op("@@")(text_query),
        )
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.document_id,
            ranked.c.start_line,
            ranked.c.end_line,
            func.ts_headline(
                "pg_catalog.english",
                ranked.c.content,
                text_query,
                "MaxFragments=1,MinWords=12,MaxWords=36,ShortWord=2",
            ).label("content"),
        )
        .where(ranked.c.position <= 3)
        .order_by(ranked.c.document_id, ranked.c.position)
    ).all()
    snippets: defaultdict[UUID, list[PaperSearchSnippet]] = defaultdict(list)
    for document_id, start_line, end_line, content in rows:
        excerpt = plain_query_excerpt(
            content,
            query,
            limit=240,
        )
        if excerpt is None:
            continue
        snippets[document_id].append(
            PaperSearchSnippet(
                text=excerpt,
                start_line=start_line,
                end_line=end_line,
            )
        )
    return dict(snippets)


class PostgresPaperSearch:
    """Authorization-first exact, fuzzy, full-text, and semantic retrieval."""

    _CANDIDATE_LIMIT = 500
    _RRF_K = 60

    def __init__(self, db: Session, *, semantic: bool = True) -> None:
        self._db = db
        self._semantic = semantic

    def _filters(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> list[ColumnElement[bool]]:
        conditions = [_visibility_condition(actor=actor, collection=request.collection)]
        if request.filters.published_from is not None:
            conditions.append(Document.publish_date >= request.filters.published_from)
        if request.filters.published_to is not None:
            conditions.append(Document.publish_date <= request.filters.published_to)
        if request.filters.personal_statuses:
            conditions.append(
                exists(
                    select(LibraryPaper.id).where(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                        LibraryPaper.status.in_(
                            [value.value for value in request.filters.personal_statuses]
                        ),
                    )
                )
            )
        if request.filters.personal_tag_ids:
            conditions.append(
                exists(
                    select(LibraryPaperTag.library_paper_id)
                    .join(
                        LibraryPaper,
                        LibraryPaper.id == LibraryPaperTag.library_paper_id,
                    )
                    .join(PaperTag, PaperTag.id == LibraryPaperTag.tag_id)
                    .where(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                        LibraryPaperTag.tag_id.in_(request.filters.personal_tag_ids),
                        PaperTag.user_id == actor.id,
                    )
                )
            )
        return conditions

    def _semantic_coverage(
        self,
        *,
        conditions: list[ColumnElement[bool]],
    ) -> tuple[int, int, float]:
        total = int(
            self._db.scalar(select(func.count(Document.id)).where(*conditions)) or 0
        )
        semantic = int(
            self._db.scalar(
                select(func.count(DocumentSearchEmbedding.document_id))
                .join(Document, Document.id == DocumentSearchEmbedding.document_id)
                .where(
                    *conditions,
                    DocumentSearchEmbedding.model_revision == EMBEDDING_MODEL_REVISION,
                )
            )
            or 0
        )
        return total, semantic, semantic / total if total else 0

    def _ranking(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> _SearchRanking:
        conditions = self._filters(actor=actor, request=request)
        plan = _query_plan(request.query)
        text_query = func.websearch_to_tsquery("pg_catalog.english", request.query)
        exact_metadata = _metadata_exact_condition(plan)
        similarity = func.similarity(Document.search_text_compact, plan.compact)
        candidate_match = (
            or_(exact_metadata, similarity >= _TRIGRAM_SIMILARITY_MIN)
            if plan.hybrid
            else exact_metadata
        )
        candidate_statement = select(
            Document.id, exact_metadata.label("exact_metadata")
        ).where(*conditions, candidate_match)
        if plan.hybrid:
            candidate_statement = candidate_statement.order_by(
                case((exact_metadata, 0), else_=1),
                similarity.desc(),
                Document.id,
            )
        else:
            candidate_statement = candidate_statement.order_by(Document.id)
        fuzzy_candidates = [
            (document_id, bool(exact))
            for document_id, exact in self._db.execute(
                candidate_statement.limit(self._CANDIDATE_LIMIT)
            ).tuples()
        ]
        full_text_ids = (
            list(
                self._db.scalars(
                    select(Document.id)
                    .where(*conditions, Document.ts_vector.op("@@")(text_query))
                    .order_by(
                        func.ts_rank_cd(Document.ts_vector, text_query).desc(),
                        Document.id,
                    )
                    .limit(self._CANDIDATE_LIMIT)
                ).all()
            )
            if plan.hybrid
            else []
        )
        has_exact_metadata = any(exact for _document_id, exact in fuzzy_candidates)
        lexical_ids = {document_id for document_id, _exact in fuzzy_candidates} | set(
            full_text_ids
        )

        semantic_candidates: list[tuple[UUID, float]] = []
        embedder = try_local_embedder() if self._semantic and plan.hybrid else None
        if embedder is not None:
            try:
                query_embedding = embedder.embed_query(request.query)
                distance = DocumentSearchEmbedding.embedding.cosine_distance(
                    query_embedding
                )
                semantic_conditions: list[ColumnElement[bool]] = [
                    *conditions,
                    DocumentSearchEmbedding.model_revision == EMBEDDING_MODEL_REVISION,
                ]
                if has_exact_metadata:
                    semantic_conditions.append(
                        Document.id.in_(sorted(lexical_ids, key=str))
                    )
                semantic_candidates = [
                    (document_id, float(candidate_distance))
                    for document_id, candidate_distance in self._db.execute(
                        select(Document.id, distance.label("cosine_distance"))
                        .join(
                            DocumentSearchEmbedding,
                            DocumentSearchEmbedding.document_id == Document.id,
                        )
                        .where(*semantic_conditions)
                        .order_by(distance, Document.id)
                        .limit(self._CANDIDATE_LIMIT)
                    ).tuples()
                ]
            except Exception:
                logger.exception("paper.search.semantic_lane_failed")
        semantic_ids = _accepted_semantic_candidates(
            semantic_candidates,
            lexical_ids=lexical_ids,
            has_exact_metadata=has_exact_metadata,
        )

        scores: defaultdict[UUID, float] = defaultdict(float)
        retrieval_modes: defaultdict[UUID, set[RetrievalMode]] = defaultdict(set)

        for rank, (document_id, exact) in enumerate(fuzzy_candidates, start=1):
            scores[document_id] += (1.2 if exact else 0.65) / (self._RRF_K + rank)
            if exact:
                scores[document_id] += 1
                retrieval_modes[document_id].add("exact")
            else:
                retrieval_modes[document_id].add("fuzzy")
        for rank, document_id in enumerate(full_text_ids, start=1):
            scores[document_id] += 1.1 / (self._RRF_K + rank)
            retrieval_modes[document_id].add("full_text")
        for rank, document_id in enumerate(semantic_ids, start=1):
            scores[document_id] += 1 / (self._RRF_K + rank)
            retrieval_modes[document_id].add("semantic")

        ranked_ids = sorted(scores, key=lambda item: (-scores[item], str(item)))
        if request.sort is PaperSearchSort.RECENT and ranked_ids:
            ranked_ids = list(
                self._db.scalars(
                    select(Document.id)
                    .where(Document.id.in_(ranked_ids))
                    .order_by(Document.created_at.desc(), Document.id)
                ).all()
            )
        return _SearchRanking(
            conditions=conditions,
            text_query=text_query,
            retrieval_modes=dict(retrieval_modes),
            semantic_ids=semantic_ids,
            ranked_ids=ranked_ids,
        )

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse:
        ranking = self._ranking(actor=actor, request=request)
        plan = _query_plan(request.query)
        ranked_ids = ranking.ranked_ids
        page_ids = ranked_ids[request.offset : request.offset + request.limit]
        actor_library_entry = aliased(
            LibraryPaper,
            name="actor_library_entry",
        )
        rows = self._db.execute(
            select(Document, actor_library_entry)
            .outerjoin(
                actor_library_entry,
                and_(
                    actor_library_entry.document_id == Document.id,
                    actor_library_entry.user_id == actor.id,
                ),
            )
            .where(Document.id.in_(page_ids))
            .options(selectinload(actor_library_entry.tags))
        ).all()
        documents = {document.id: (document, entry) for document, entry in rows}
        page_rows = [documents[document_id] for document_id in page_ids]
        _visible_total, _semantic_total, semantic_coverage = self._semantic_coverage(
            conditions=ranking.conditions
        )
        document_ids = [document.id for document, _entry in page_rows]
        passages = (
            _matching_passages(
                self._db,
                document_ids=document_ids,
                text_query=ranking.text_query,
                query=request.query,
            )
            if plan.hybrid
            else {}
        )

        items: list[PaperSearchResult] = []
        for document, library_entry in page_rows:
            snippets = passages.get(document.id, [])
            has_matching_passage = bool(snippets)
            items.append(
                PaperSearchResult(
                    document_id=document.id,
                    title=document.title,
                    authors=document.authors,
                    abstract=document.abstract,
                    summary=document.summary,
                    keywords=document.keywords or [],
                    doi=document.doi,
                    journal=document.journal,
                    status=(
                        library_entry.status
                        if library_entry is not None
                        else document.processing_status
                    ),
                    publish_date=document.publish_date,
                    created_at=document.created_at,
                    last_accessed_at=(
                        library_entry.last_accessed_at
                        if library_entry is not None
                        else document.created_at
                    ),
                    preview_url=(
                        s3_service.generate_presigned_url(document.preview_s3_key)
                        if document.preview_s3_key
                        else None
                    ),
                    personal_status=(
                        library_entry.status if library_entry is not None else None
                    ),
                    personal_tags=(
                        [
                            LibraryPaperTagResponse(
                                id=tag.id,
                                name=tag.name,
                                color=tag.color,
                            )
                            for tag in library_entry.tags
                        ]
                        if library_entry is not None
                        else []
                    ),
                    personal_last_accessed_at=(
                        library_entry.last_accessed_at
                        if library_entry is not None
                        else None
                    ),
                    matched_fields=_matching_fields(
                        document,
                        plan,
                        has_passage=has_matching_passage,
                    ),
                    retrieval_modes=sorted(ranking.retrieval_modes[document.id]),
                    snippets=snippets,
                )
            )
        return PaperSearchResponse(
            items=items,
            total=len(ranked_ids),
            search_mode="hybrid" if ranking.semantic_ids else "lexical",
            semantic_index_coverage=semantic_coverage,
        )

    def search_candidates(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchCandidatePage:
        """Project one ranked window without hydrating full Document ORM rows."""

        ranking = self._ranking(actor=actor, request=request)
        plan = _query_plan(request.query)
        page_ids = ranking.ranked_ids[request.offset : request.offset + request.limit]
        if not page_ids:
            return PaperSearchCandidatePage(items=[], total=len(ranking.ranked_ids))
        actor_library_entry = aliased(
            LibraryPaper,
            name="knowledge_actor_library_entry",
        )
        rows = list(
            self._db.execute(
                select(
                    Document.id.label("document_id"),
                    func.left(Document.title, _CANDIDATE_TITLE_CHARACTERS).label(
                        "title"
                    ),
                    func.left(Document.abstract, _CANDIDATE_TEXT_CHARACTERS).label(
                        "abstract"
                    ),
                    func.left(Document.summary, _CANDIDATE_TEXT_CHARACTERS).label(
                        "summary"
                    ),
                    Document.created_at.label("created_at"),
                    func.coalesce(
                        actor_library_entry.last_accessed_at,
                        Document.created_at,
                    ).label("last_accessed_at"),
                )
                .outerjoin(
                    actor_library_entry,
                    and_(
                        actor_library_entry.document_id == Document.id,
                        actor_library_entry.user_id == actor.id,
                    ),
                )
                .where(Document.id.in_(page_ids))
            )
            .mappings()
            .all()
        )
        projected = {cast(UUID, row["document_id"]): row for row in rows}
        passages = (
            _matching_passages(
                self._db,
                document_ids=page_ids,
                text_query=ranking.text_query,
                query=request.query,
            )
            if plan.hybrid
            else {}
        )
        items: list[PaperSearchCandidate] = []
        for document_id in page_ids:
            row = projected.get(document_id)
            if row is None:
                continue
            title = self._candidate_text(
                cast(str | None, row["title"]),
                max_bytes=_CANDIDATE_TITLE_JSON_BYTES,
            )
            abstract = self._candidate_text(
                cast(str | None, row["abstract"]),
                max_bytes=_CANDIDATE_TEXT_JSON_BYTES,
            )
            summary = self._candidate_text(
                cast(str | None, row["summary"]),
                max_bytes=_CANDIDATE_TEXT_JSON_BYTES,
            )
            snippets = [
                PaperSearchSnippet(
                    text=json_bounded_prefix(
                        snippet.text,
                        max_bytes=_CANDIDATE_TEXT_JSON_BYTES,
                    ),
                    start_line=snippet.start_line,
                    end_line=snippet.end_line,
                )
                for snippet in passages.get(document_id, [])[:3]
            ]
            if not snippets:
                fallback = abstract or summary
                if fallback is not None:
                    snippets = [PaperSearchSnippet(text=fallback)]
            items.append(
                PaperSearchCandidate(
                    document_id=document_id,
                    title=title,
                    abstract=abstract,
                    created_at=cast(datetime, row["created_at"]),
                    last_accessed_at=cast(datetime, row["last_accessed_at"]),
                    snippets=snippets,
                )
            )
        return PaperSearchCandidatePage(
            items=items,
            total=len(ranking.ranked_ids),
        )

    @staticmethod
    def _candidate_text(value: str | None, *, max_bytes: int) -> str | None:
        return (
            json_bounded_prefix(value, max_bytes=max_bytes)
            if value is not None
            else None
        )

    def stats(
        self,
        *,
        actor: Actor,
    ) -> PaperSearchStats:
        total, semantic, coverage = self._semantic_coverage(
            conditions=[accessible_document_condition(user_id=actor.id)]
        )
        return PaperSearchStats(
            total_papers=total,
            searchable_items=total,
            semantic_items=semantic,
            semantic_index_coverage=coverage,
        )
