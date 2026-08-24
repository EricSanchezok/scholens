"""Composed PostgreSQL search/reading/collaboration verification journey."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.adapters.paper_search import PostgresPaperSearch
from app.bootstrap.adapters.paper_search_access import SqlPaperSearchAccess
from app.database.database import SessionLocal
from app.database.models import AuthUser
from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperSearchRequest,
    SelectedPaperCollection,
)
from app.modules.papers.application.search import SearchCursorCodec, SearchPapers
from app.modules.papers.infrastructure.content_gateway import (
    SqlAlchemyPaperContentGateway,
)
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.modules.projects.infrastructure.document_visibility import (
    SqlProjectDocumentVisibility,
)
from app.shared.application import Actor
from app.shared.domain import AppError

TITLE_DOCUMENT_ID = UUID("10000000-0000-0000-0000-000000000001")
BODY_DOCUMENT_ID = UUID("10000000-0000-0000-0000-000000000002")
PROJECT_DOCUMENT_ID = UUID("10000000-0000-0000-0000-000000000003")
PROJECT_ID = UUID("10000000-0000-0000-0000-000000000010")


def _actor(db: Session, email: str) -> Actor:
    user = db.scalar(select(AuthUser).where(AuthUser.email == email))
    if user is None:
        raise AssertionError(f"search fixture user is missing: {email}")
    return Actor.from_identity_projection(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=str(user.status),
        email_verified=user.email_verified_at is not None,
        locale=user.profile.locale if user.profile else None,
        is_admin=user.profile.is_admin if user.profile else False,
        is_blocked=user.profile.is_blocked if user.profile else False,
    )


def verify_paper_search() -> None:
    with SessionLocal() as db:
        owner = _actor(db, "ci-search-owner@example.com")
        collaborator = _actor(db, "ci-search-collaborator@example.com")
        outsider = _actor(db, "ci-search-outsider@example.com")
        search = SearchPapers(
            PostgresPaperSearch(db),
            SearchCursorCodec("integration-search-cursor-secret-value"),
            SqlPaperSearchAccess(db),
        )
        content = PaperContentCapabilities(
            SqlAlchemyPaperContentGateway(db),
            ListAccessibleProjectDocuments(SqlProjectDocumentVisibility(db)),
        )

        first = search(
            actor=owner,
            request=PaperSearchRequest(query="neural retrieval", limit=1),
        )
        assert first.total == 3
        assert first.items[0].document_id == TITLE_DOCUMENT_ID
        assert first.items[0].matched_fields == ["title"]
        assert first.items[0].snippets == []
        assert first.next_cursor is not None
        second = search(
            actor=owner,
            request=PaperSearchRequest(
                query="neural retrieval", limit=1, cursor=first.next_cursor
            ),
        )
        assert second.items[0].document_id != first.items[0].document_id

        short_numeric = search(
            actor=owner,
            request=PaperSearchRequest(query="23"),
        )
        assert short_numeric.items == [] and short_numeric.total == 0

        library = search(
            actor=owner,
            request=PaperSearchRequest(
                query="neural retrieval", collection=LibraryPaperCollection()
            ),
        )
        assert {item.document_id for item in library.items} == {
            TITLE_DOCUMENT_ID,
            BODY_DOCUMENT_ID,
            PROJECT_DOCUMENT_ID,
        }
        body = next(
            item for item in library.items if item.document_id == BODY_DOCUMENT_ID
        )
        assert body.snippets[0].start_line == 40

        project = search(
            actor=collaborator,
            request=PaperSearchRequest(
                query="neural retrieval",
                collection=SelectedPaperCollection(project_ids=[PROJECT_ID]),
            ),
        )
        assert [item.document_id for item in project.items] == [PROJECT_DOCUMENT_ID]
        project_paper = content.read(
            actor=collaborator,
            document_id=PROJECT_DOCUMENT_ID,
            project_id=PROJECT_ID,
        )
        assert project_paper.raw_content == "project-only fixture"

        restricted = search(
            actor=owner,
            request=PaperSearchRequest(
                query="neural retrieval",
                collection=SelectedPaperCollection(document_ids=[BODY_DOCUMENT_ID]),
            ),
        )
        assert [item.document_id for item in restricted.items] == [BODY_DOCUMENT_ID]
        stemmed = search(
            actor=owner,
            request=PaperSearchRequest(
                query="neural retrieving",
                collection=SelectedPaperCollection(document_ids=[BODY_DOCUMENT_ID]),
            ),
        )
        assert [item.document_id for item in stemmed.items] == [BODY_DOCUMENT_ID]
        assert "neural retrieval" in stemmed.items[0].snippets[0].text
        hidden = search(
            actor=outsider, request=PaperSearchRequest(query="neural retrieval")
        )
        assert hidden.items == [] and hidden.total == 0
        try:
            content.read(
                actor=outsider,
                document_id=PROJECT_DOCUMENT_ID,
                project_id=PROJECT_ID,
            )
        except AppError as exc:
            assert exc.code == "paper_not_found"
        else:
            raise AssertionError("outsider unexpectedly read a project document")


__all__ = ["verify_paper_search"]
