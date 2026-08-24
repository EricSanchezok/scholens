from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.bootstrap.adapters.library_outputs import SqlAlchemyLibraryOutputsGateway
from app.modules.papers.application.contracts.documents import (
    LibraryOutputSort,
)
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadCapabilities,
    AnnotationThreadContent,
    ProjectResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
)
from app.modules.papers.application.library import LibraryPageDirection
from app.modules.research.application.items import ResearchItemPageAccess
from app.modules.research.application.legacy_outputs import (
    LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES,
    LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES,
    LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES,
    LegacyResearchListItemSize,
    hostile_json_string_utf8_upper_bound,
    legacy_research_list_payload_json_utf8_upper_bound,
)
from app.modules.research.infrastructure.models import ResearchItem
from app.shared.domain import AppError
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from sqlalchemy.dialects import postgresql


def _row(*, item_id, title: str = "Citation", source_title: str = "Paper"):
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    return {
        "item_id": item_id,
        "kind": ResearchItemKind.CITATION.value,
        "audience_type": ResearchAudienceType.DOCUMENT.value,
        "audience_document_id": uuid4(),
        "audience_project_id": None,
        "title": title,
        "source_title": source_title,
        "sort_key": now,
    }


def _access(
    item_id,
    *,
    payload_upper_bound: int,
    revision: str = "a" * 64,
) -> ResearchItemPageAccess:
    return ResearchItemPageAccess(
        item_id=item_id,
        kind=ResearchItemKind.CITATION,
        revision=revision,
        durable_json_utf8_upper_bound=payload_upper_bound,
        legacy_payload_json_utf8_upper_bound=payload_upper_bound,
    )


def test_legacy_list_budget_counts_fixed_overhead_once_and_escapes_hostile_text() -> (
    None
):
    hostile = '\x00"\\🙂'
    first = LegacyResearchListItemSize(
        item_json_utf8_upper_bound=100,
        title=hostile,
        source_title=hostile,
        wrapped=True,
    )
    second = LegacyResearchListItemSize(item_json_utf8_upper_bound=200)

    bound = legacy_research_list_payload_json_utf8_upper_bound((first, second))

    assert bound == (
        LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES
        + first.payload_json_utf8_upper_bound()
        + second.payload_json_utf8_upper_bound()
    )
    assert hostile_json_string_utf8_upper_bound(hostile) >= len(
        ('"' + hostile + '"').encode("utf-8")
    )


def test_legacy_item_fixed_allowances_cover_maximum_structural_shape() -> None:
    item_id = uuid4()
    maximum_time = datetime.max.replace(tzinfo=UTC)
    maximum_user_id = 2**63 - 1
    empty_creator = ResearchCreatorResponse(
        id=maximum_user_id,
        display_name="",
    )
    comment = AnnotationCommentResponse(
        id=item_id,
        thread_id=item_id,
        content="",
        role="assistant",
        created_by=empty_creator,
        created_at=maximum_time,
        updated_at=maximum_time,
        can_edit=True,
        can_delete=True,
    )
    item = ResearchItemResponse(
        id=item_id,
        kind=ResearchItemKind.ANNOTATION_THREAD,
        audience=ProjectResearchAudience(project_id=item_id),
        target_document_id=item_id,
        created_by=empty_creator,
        created_at=maximum_time,
        updated_at=maximum_time,
        capabilities=ResearchItemCapabilities(edit=True, delete=True),
        annotation_thread=AnnotationThreadContent(
            quote_text="",
            position=None,
            color=AnnotationColor.YELLOW,
            role="assistant",
            mode=AnnotationThreadMode.DISCUSSION,
            comment_count=1,
            last_activity_at=maximum_time,
            status=AnnotationThreadStatus.RESOLVED,
            resolved_by=empty_creator,
            resolved_at=maximum_time,
            capabilities=AnnotationThreadCapabilities(
                reply=True,
                recolor=True,
                resolve=True,
                reopen=True,
                delete=True,
            ),
            comments=[comment],
        ),
    )

    encoded = json.dumps(
        item.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(encoded) <= (
        LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES
        + LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES
    )


def test_legacy_library_page_rejects_before_relationship_hydration() -> None:
    item_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.mappings.return_value.all.return_value = [
        _row(item_id=item_id, title='\x00"\\' * 100)
    ]
    gateway = SqlAlchemyLibraryOutputsGateway(db)

    with (
        patch(
            "app.bootstrap.adapters.library_outputs.research_repository.authorize_page",
            return_value=_access(item_id, payload_upper_bound=100_000),
        ),
        pytest.raises(AppError) as raised,
    ):
        gateway.list(
            user_id=7,
            query="Paper",
            kinds=(),
            sort=LibraryOutputSort.UPDATED_DESC,
            limit=100,
            direction=LibraryPageDirection.FORWARD,
            position=None,
            maximum_payload_json_bytes=62_805,
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    assert raised.value.details["replacement_tool"] == (
        "list_research_output_summaries"
    )
    db.scalars.assert_not_called()
    statement = db.execute.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "for update of research_items" in sql
    assert "lower(" in sql
    assert "like '%%paper%%'" in sql
    assert "documents.title" in sql
    assert "projects.title" in sql
    assert "personal library" in sql


def test_legacy_library_page_can_prepare_more_than_summary_catalog_limit() -> None:
    rows = [_row(item_id=uuid4(), title=f"Citation {index}") for index in range(26)]
    items = [
        ResearchItem(
            id=row["item_id"],
            kind=ResearchItemKind.CITATION.value,
            audience_type=ResearchAudienceType.DOCUMENT.value,
            created_by_id=7,
        )
        for row in rows
    ]
    db = MagicMock()
    db.scalar.return_value = len(rows)
    db.execute.return_value.mappings.return_value.all.return_value = rows
    db.scalars.return_value.unique.return_value.all.return_value = items
    gateway = SqlAlchemyLibraryOutputsGateway(db)
    responses = [MagicMock() for _ in rows]

    def access(*_args: object, item_id, **_kwargs: object) -> ResearchItemPageAccess:
        return _access(item_id, payload_upper_bound=1_300)

    with (
        patch(
            "app.bootstrap.adapters.library_outputs.research_repository.authorize_page",
            side_effect=access,
        ),
        patch.object(gateway, "_response_from_scalar", side_effect=responses),
    ):
        page = gateway.list(
            user_id=7,
            query=None,
            kinds=(),
            sort=LibraryOutputSort.UPDATED_DESC,
            limit=100,
            direction=LibraryPageDirection.FORWARD,
            position=None,
            maximum_payload_json_bytes=62_805,
        )

    assert len(page.items) == 26
    assert page.items == responses
    assert len(page.positions) == 26
    assert page.total_count == 26
    assert db.scalars.call_count == 1


def test_legacy_library_page_rejects_revision_race_after_hydration() -> None:
    row = _row(item_id=uuid4())
    item = ResearchItem(
        id=row["item_id"],
        kind=ResearchItemKind.CITATION.value,
        audience_type=ResearchAudienceType.DOCUMENT.value,
        created_by_id=7,
    )
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.mappings.return_value.all.return_value = [row]
    db.scalars.return_value.unique.return_value.all.return_value = [item]
    gateway = SqlAlchemyLibraryOutputsGateway(db)

    with (
        patch(
            "app.bootstrap.adapters.library_outputs.research_repository.authorize_page",
            side_effect=[
                _access(row["item_id"], payload_upper_bound=100, revision="a" * 64),
                _access(row["item_id"], payload_upper_bound=100, revision="b" * 64),
            ],
        ),
        patch.object(gateway, "_response_from_scalar", return_value=MagicMock()),
        pytest.raises(AppError) as raised,
    ):
        gateway.list(
            user_id=7,
            query=None,
            kinds=(),
            sort=LibraryOutputSort.UPDATED_DESC,
            limit=100,
            direction=LibraryPageDirection.FORWARD,
            position=None,
            maximum_payload_json_bytes=62_805,
        )

    assert raised.value.code == "research_output_snapshot_changed"


def test_legacy_title_cursor_uses_historical_response_fallback_key() -> None:
    row = _row(item_id=uuid4(), title="Citation")
    row["sort_key"] = ""
    item = ResearchItem(
        id=row["item_id"],
        kind=ResearchItemKind.CITATION.value,
        audience_type=ResearchAudienceType.DOCUMENT.value,
        created_by_id=7,
    )
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value.mappings.return_value.all.return_value = [row]
    db.scalars.return_value.unique.return_value.all.return_value = [item]
    gateway = SqlAlchemyLibraryOutputsGateway(db)

    with (
        patch(
            "app.bootstrap.adapters.library_outputs.research_repository.authorize_page",
            return_value=_access(row["item_id"], payload_upper_bound=100),
        ),
        patch.object(gateway, "_response_from_scalar", return_value=MagicMock()),
    ):
        page = gateway.list(
            user_id=7,
            query=None,
            kinds=(),
            sort=LibraryOutputSort.TITLE_ASC,
            limit=100,
            direction=LibraryPageDirection.FORWARD,
            position=None,
            maximum_payload_json_bytes=62_805,
        )

    assert page.positions[0].key == "citation"
