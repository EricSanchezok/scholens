from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.bootstrap.adapters.research_repository import research_repository
from app.modules.research.application.items import ResearchItemPageAccess
from app.shared.domain.enums import ResearchItemKind
from sqlalchemy.dialects import postgresql


def _audio_access_row(*, payload_digest: str = "payload-digest") -> SimpleNamespace:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    return SimpleNamespace(
        item_id=uuid4(),
        kind=ResearchItemKind.AUDIO_OVERVIEW.value,
        item_updated_at=now,
        annotation_updated_at=None,
        citation_updated_at=None,
        audio_updated_at=now,
        table_updated_at=None,
        payload_digest=payload_digest,
        payload_json_utf8_bytes=100,
        payload_string_utf8_bytes=900,
        creator_updated_at=now,
        creator_utf8_bytes=50,
        resolved_user_updated_at=None,
        resolved_user_utf8_bytes=0,
        audio_object_key="research/audio.mp3",
    )


def test_research_page_access_returns_bounded_revision_and_size_facts() -> None:
    row = _audio_access_row()
    db = MagicMock()
    db.execute.return_value.one_or_none.return_value = row

    with patch(
        "app.bootstrap.adapters.research_repository.s3_service.generate_presigned_url",
        return_value="https://signed.example/audio",
    ) as sign:
        access = research_repository.authorize_page(
            db,
            item_id=row.item_id,
            user_id=7,
        )

    assert access.item_id == row.item_id
    assert access.kind is ResearchItemKind.AUDIO_OVERVIEW
    assert access.durable_json_utf8_upper_bound == 6 * 1_050 + 65_536
    assert access.legacy_payload_json_utf8_upper_bound == (100 + 6 * 950 + 896 + 4_096)
    assert len(access.revision) == 64
    assert access.access_url == "https://signed.example/audio"
    sign.assert_called_once_with("research/audio.mp3")

    statement = db.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "item_id",
        "kind",
        "item_updated_at",
        "annotation_updated_at",
        "citation_updated_at",
        "audio_updated_at",
        "table_updated_at",
        "payload_digest",
        "payload_json_utf8_bytes",
        "payload_string_utf8_bytes",
        "creator_updated_at",
        "creator_utf8_bytes",
        "resolved_user_updated_at",
        "resolved_user_utf8_bytes",
        "audio_object_key",
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
        )
    ).lower()
    assert "research_items.*" not in sql
    assert "md5(" in sql
    assert "octet_length(" in sql


def test_legacy_read_locks_scalar_item_before_size_preflight() -> None:
    item_id = uuid4()
    expected = ResearchItemPageAccess(
        item_id=item_id,
        kind=ResearchItemKind.CITATION,
        revision="a" * 64,
        durable_json_utf8_upper_bound=8_192,
        legacy_payload_json_utf8_upper_bound=4_096,
    )
    db = MagicMock()
    db.scalar.return_value = item_id

    with patch.object(research_repository, "authorize_page", return_value=expected):
        result = research_repository.lock_legacy_read(
            db,
            item_id=item_id,
            user_id=7,
        )

    assert result == expected
    statement = db.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "select scholens.research_items.id" in sql
    assert "for update of research_items" in sql
    assert "research_items.*" not in sql


def test_legacy_audio_preflight_does_not_sign_before_budget_acceptance() -> None:
    row = _audio_access_row()
    db = MagicMock()
    db.scalar.return_value = row.item_id
    db.execute.return_value.one_or_none.return_value = row

    with patch(
        "app.bootstrap.adapters.research_repository.s3_service.generate_presigned_url"
    ) as sign:
        access = research_repository.lock_legacy_read(
            db,
            item_id=row.item_id,
            user_id=7,
        )

    assert access.access_url is None
    assert access.legacy_payload_json_utf8_upper_bound is not None
    sign.assert_not_called()


def test_research_page_revision_changes_with_nested_payload_digest() -> None:
    first = _audio_access_row(payload_digest="first")
    second = SimpleNamespace(**vars(first))
    second.payload_digest = "second"
    db = MagicMock()
    db.execute.return_value.one_or_none.side_effect = [first, second]

    with patch(
        "app.bootstrap.adapters.research_repository.s3_service.generate_presigned_url",
        return_value="https://signed.example/audio",
    ):
        first_access = research_repository.authorize_page(
            db,
            item_id=first.item_id,
            user_id=7,
        )
        second_access = research_repository.authorize_page(
            db,
            item_id=first.item_id,
            user_id=7,
        )

    assert first_access.revision != second_access.revision
