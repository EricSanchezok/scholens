"""Cross-domain PostgreSQL projection for canonical paper search."""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import Literal
import unicodedata
from uuid import UUID

from scholens_ai import EMBEDDING_MODEL_REVISION, try_local_embedder

from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.search import (
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
from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

logger = logging.getLogger(__name__)

RetrievalMode = Literal["exact", "full_text", "fuzzy", "semantic"]


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


def _matching_fields(document: Document, query: str, *, has_passage: bool) -> list[str]:
    needle = query.casefold()
    fields: list[str] = []
    candidates = (
        ("title", document.title),
        ("authors", " ".join(document.authors or [])),
        ("keywords", " ".join(document.keywords or [])),
        ("abstract", document.abstract),
    )
    for name, value in candidates:
        if value and needle in value.casefold():
            fields.append(name)
    if has_passage or (
        document.raw_content and needle in document.raw_content.casefold()
    ):
        fields.append("body")
    return fields


def _fallback_snippet(document: Document, query: str) -> PaperSearchSnippet | None:
    content = document.raw_content or document.abstract or document.summary
    if not content:
        return None
    lines = content.splitlines()
    needle = query.casefold()
    for index, line in enumerate(lines):
        if needle in line.casefold():
            start = max(index - 1, 0)
            end = min(index + 2, len(lines))
            return PaperSearchSnippet(
                text="\n".join(lines[start:end])[:1_200],
                start_line=start + 1,
                end_line=end,
            )
    return PaperSearchSnippet(text=content[:1_200])


def _compact_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _matching_passages(
    db: Session,
    *,
    document_ids: list[UUID],
    text_query: object,
) -> dict[UUID, list[PaperSearchSnippet]]:
    if not document_ids:
        return {}
    passage_rank = func.ts_rank_cd(DocumentPassage.ts_vector, text_query)
    ranked = (
        select(
            DocumentPassage.document_id.label("document_id"),
            DocumentPassage.start_line.label("start_line"),
            DocumentPassage.end_line.label("end_line"),
            DocumentPassage.content.label("content"),
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
            ranked.c.content,
        )
        .where(ranked.c.position <= 3)
        .order_by(ranked.c.document_id, ranked.c.position)
    ).all()
    snippets: defaultdict[UUID, list[PaperSearchSnippet]] = defaultdict(list)
    for document_id, start_line, end_line, content in rows:
        snippets[document_id].append(
            PaperSearchSnippet(
                text=content[:1_200],
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

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse:
        conditions = self._filters(actor=actor, request=request)
        text_query = func.websearch_to_tsquery("pg_catalog.english", request.query)
        compact_query = _compact_query(request.query)
        similarity = func.similarity(Document.search_text_compact, compact_query)
        contains_query = Document.search_text_compact.contains(compact_query)

        fuzzy_candidates: list[tuple[UUID, bool]] = (
            [
                (document_id, bool(exact))
                for document_id, exact in self._db.execute(
                    select(Document.id, contains_query.label("contains_query"))
                    .where(
                        *conditions,
                        or_(contains_query, similarity >= 0.08),
                    )
                    .order_by(
                        case((contains_query, 0), else_=1),
                        similarity.desc(),
                        Document.id,
                    )
                    .limit(self._CANDIDATE_LIMIT)
                ).tuples()
            ]
            if compact_query
            else []
        )
        full_text_ids = list(
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

        semantic_ids: list[UUID] = []
        embedder = try_local_embedder() if self._semantic else None
        if embedder is not None:
            try:
                query_embedding = embedder.embed_query(request.query)
                semantic_ids = list(
                    self._db.scalars(
                        select(Document.id)
                        .join(
                            DocumentSearchEmbedding,
                            DocumentSearchEmbedding.document_id == Document.id,
                        )
                        .where(
                            *conditions,
                            DocumentSearchEmbedding.model_revision
                            == EMBEDDING_MODEL_REVISION,
                        )
                        .order_by(
                            DocumentSearchEmbedding.embedding.cosine_distance(
                                query_embedding
                            ),
                            Document.id,
                        )
                        .limit(self._CANDIDATE_LIMIT)
                    ).all()
                )
            except Exception:
                logger.exception("paper.search.semantic_lane_failed")

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
            conditions=conditions
        )
        document_ids = [document.id for document, _entry in page_rows]
        passages = _matching_passages(
            self._db,
            document_ids=document_ids,
            text_query=text_query,
        )

        items: list[PaperSearchResult] = []
        for document, library_entry in page_rows:
            snippets = passages.get(document.id, [])
            has_matching_passage = bool(snippets)
            if not snippets:
                fallback = _fallback_snippet(document, request.query)
                if fallback is not None:
                    snippets = [fallback]
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
                        request.query,
                        has_passage=has_matching_passage,
                    ),
                    retrieval_modes=sorted(retrieval_modes[document.id]),
                    snippets=snippets,
                )
            )
        return PaperSearchResponse(
            items=items,
            total=len(ranked_ids),
            search_mode="hybrid" if semantic_ids else "lexical",
            semantic_index_coverage=semantic_coverage,
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
