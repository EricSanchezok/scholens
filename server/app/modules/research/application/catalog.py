"""Bounded Research-output catalog queries independent of transport and storage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from app.modules.research.application.contracts import (
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind


class ResearchOutputCatalogScopeKind(StrEnum):
    LIBRARY = "library"
    PERSONAL_LIBRARY = "personal_library"
    PROJECT = "project"
    PAPER = "paper"


@dataclass(frozen=True, slots=True)
class ResearchOutputCatalogScope:
    kind: ResearchOutputCatalogScopeKind
    document_id: UUID | None = None
    project_id: UUID | None = None

    def __post_init__(self) -> None:
        valid = (
            (
                self.kind
                in {
                    ResearchOutputCatalogScopeKind.LIBRARY,
                    ResearchOutputCatalogScopeKind.PERSONAL_LIBRARY,
                }
                and self.document_id is None
                and self.project_id is None
            )
            or (
                self.kind is ResearchOutputCatalogScopeKind.PROJECT
                and self.document_id is None
                and self.project_id is not None
            )
            or (
                self.kind is ResearchOutputCatalogScopeKind.PAPER
                and self.document_id is not None
            )
        )
        if not valid:
            raise ValueError("research-output scope identifiers are inconsistent")

    @classmethod
    def library(cls) -> ResearchOutputCatalogScope:
        return cls(kind=ResearchOutputCatalogScopeKind.LIBRARY)

    @classmethod
    def personal_library(cls) -> ResearchOutputCatalogScope:
        """Select outputs that belong to the actor's exact personal Library."""

        return cls(kind=ResearchOutputCatalogScopeKind.PERSONAL_LIBRARY)

    @classmethod
    def project(cls, project_id: UUID) -> ResearchOutputCatalogScope:
        return cls(
            kind=ResearchOutputCatalogScopeKind.PROJECT,
            project_id=project_id,
        )

    @classmethod
    def paper(
        cls,
        document_id: UUID,
        *,
        project_id: UUID | None = None,
    ) -> ResearchOutputCatalogScope:
        return cls(
            kind=ResearchOutputCatalogScopeKind.PAPER,
            document_id=document_id,
            project_id=project_id,
        )


class ResearchOutputCatalogSort(StrEnum):
    UPDATED_DESC = "updated_desc"
    UPDATED_ASC = "updated_asc"
    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"


class ResearchOutputPageDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True, slots=True)
class ResearchOutputPagePosition:
    key: str
    item_id: UUID


@dataclass(frozen=True, slots=True)
class ResearchOutputSummaryPage:
    items: list[ResearchOutputSummary]
    positions: list[ResearchOutputPagePosition]
    has_more: bool
    total_count: int | None


class ResearchOutputCatalogGateway(Protocol):
    def get(self, *, user_id: int, item_id: UUID) -> ResearchOutputSummary: ...

    def list(
        self,
        *,
        user_id: int,
        scope: ResearchOutputCatalogScope,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        sort: ResearchOutputCatalogSort,
        limit: int,
        direction: ResearchOutputPageDirection,
        position: ResearchOutputPagePosition | None,
        include_total_count: bool = True,
    ) -> ResearchOutputSummaryPage: ...


class ResearchOutputCatalog:
    """Authorize and paginate bounded output summaries with one stable contract."""

    def __init__(
        self,
        gateway: ResearchOutputCatalogGateway,
        *,
        cursors: SignedCursorCodec,
    ) -> None:
        self._gateway = gateway
        self._cursors = cursors

    def get(self, *, actor: Actor, item_id: UUID) -> ResearchOutputSummary:
        """Return one authorized bounded scalar summary by immutable ID."""

        return self._gateway.get(user_id=actor.id, item_id=item_id)

    def list(
        self,
        *,
        actor: Actor,
        scope: ResearchOutputCatalogScope,
        query: str | None = None,
        kinds: tuple[ResearchItemKind, ...] = (),
        sort: ResearchOutputCatalogSort = ResearchOutputCatalogSort.UPDATED_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ResearchOutputSummaryListResponse:
        # The public summary tool caps pages at 25 in its input schema. The
        # retained legacy list shape permits 100 complete items, so this shared
        # scalar catalog accepts that same hard upper bound and serves it in one
        # snapshot query rather than stitching multiple moving cursor pages.
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise AppError(
                code="research_output_limit_invalid",
                message="Research-output page size must be between 1 and 100",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        normalized_query = query.strip().casefold() if query and query.strip() else None
        normalized_kinds = tuple(sorted(set(kinds), key=lambda value: value.value))
        filters: dict[str, object] = {
            "scope": self._scope_binding(scope),
            "query": normalized_query,
            "kinds": [kind.value for kind in normalized_kinds],
            "sort": sort.value,
        }
        direction, position = self._decode_cursor(
            actor=actor,
            filters=filters,
            cursor=cursor,
        )
        page = self._gateway.list(
            user_id=actor.id,
            scope=scope,
            query=normalized_query,
            kinds=normalized_kinds,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
            include_total_count=True,
        )
        if page.total_count is None:
            raise RuntimeError("paginated research-output catalog omitted total_count")
        return ResearchOutputSummaryListResponse(
            items=page.items,
            previous_cursor=self._page_cursor(
                actor=actor,
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=True,
            ),
            next_cursor=self._page_cursor(
                actor=actor,
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
                previous=False,
            ),
            total_count=page.total_count,
        )

    def candidate_page(
        self,
        *,
        actor: Actor,
        scope: ResearchOutputCatalogScope,
        query: str,
        kinds: tuple[ResearchItemKind, ...],
        limit: int,
        after: ResearchOutputPagePosition | None,
    ) -> ResearchOutputSummaryPage:
        """Return one count-free forward keyset window for a composing search."""

        if isinstance(limit, bool) or not 1 <= limit <= 25:
            raise AppError(
                code="research_output_limit_invalid",
                message="Research-output candidate limit must be between 1 and 25",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        normalized_query = query.strip().casefold()
        normalized_kinds = tuple(sorted(set(kinds), key=lambda value: value.value))
        return self._gateway.list(
            user_id=actor.id,
            scope=scope,
            query=normalized_query,
            kinds=normalized_kinds,
            sort=ResearchOutputCatalogSort.UPDATED_DESC,
            limit=limit,
            direction=ResearchOutputPageDirection.FORWARD,
            position=after,
            include_total_count=False,
        )

    def _decode_cursor(
        self,
        *,
        actor: Actor,
        filters: Mapping[str, object],
        cursor: str | None,
    ) -> tuple[ResearchOutputPageDirection, ResearchOutputPagePosition | None]:
        if cursor is None:
            return ResearchOutputPageDirection.FORWARD, None
        try:
            direction, key, item_id = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(actor=actor, filters=filters),
                arity=3,
            )
            return ResearchOutputPageDirection(direction), ResearchOutputPagePosition(
                key=key,
                item_id=UUID(item_id),
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="research_output_cursor_invalid",
                message="The research-output cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _page_cursor(
        self,
        *,
        actor: Actor,
        filters: Mapping[str, object],
        page: ResearchOutputSummaryPage,
        direction: ResearchOutputPageDirection,
        had_position: bool,
        previous: bool,
    ) -> str | None:
        if not page.positions:
            return None
        available = (
            page.has_more
            if (previous and direction is ResearchOutputPageDirection.BACKWARD)
            or (not previous and direction is ResearchOutputPageDirection.FORWARD)
            else had_position
        )
        if not available:
            return None
        target_direction = (
            ResearchOutputPageDirection.BACKWARD
            if previous
            else ResearchOutputPageDirection.FORWARD
        )
        position = page.positions[0] if previous else page.positions[-1]
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(actor=actor, filters=filters),
            values=(target_direction.value, position.key, str(position.item_id)),
        )

    @staticmethod
    def _scope_binding(scope: ResearchOutputCatalogScope) -> dict[str, str | None]:
        return {
            "kind": scope.kind.value,
            "document_id": (
                str(scope.document_id) if scope.document_id is not None else None
            ),
            "project_id": str(scope.project_id)
            if scope.project_id is not None
            else None,
        }

    @staticmethod
    def _cursor_binding(*, actor: Actor, filters: Mapping[str, object]) -> str:
        return json.dumps(
            {
                "revision": "research-output-catalog-v1",
                "user_id": actor.id,
                "filters": filters,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


__all__ = [
    "ResearchOutputCatalog",
    "ResearchOutputCatalogGateway",
    "ResearchOutputCatalogScope",
    "ResearchOutputCatalogScopeKind",
    "ResearchOutputCatalogSort",
    "ResearchOutputPageDirection",
    "ResearchOutputPagePosition",
    "ResearchOutputSummaryPage",
]
