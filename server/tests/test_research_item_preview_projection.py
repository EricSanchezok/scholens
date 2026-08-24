from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.papers.application.contracts.citation import CitationData
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadCapabilities,
    AnnotationThreadContent,
    AudioOverviewContent,
    CitationContent,
    CitationSnapshot,
    DataTableContent,
    PersonalResearchAudience,
    ResearchCreatorResponse,
    ResearchItemCapabilities,
    ResearchItemResponse,
)
from app.shared.application.json_values import normalize_json_value
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchItemKind,
)
from app.tooling.research_item_preview_projection import (
    project_research_item_preview,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)
HOSTILE = '\x00\x01"\\🙂' * 20_000


def _item(
    *,
    kind: ResearchItemKind,
    **content: object,
) -> ResearchItemResponse:
    return ResearchItemResponse(
        id=uuid4(),
        kind=kind,
        audience=PersonalResearchAudience(),
        target_document_id=uuid4(),
        created_by=ResearchCreatorResponse(id=1, display_name=HOSTILE),
        created_at=NOW,
        updated_at=NOW,
        capabilities=ResearchItemCapabilities(edit=True, delete=True),
        **content,
    )


def _wire_bytes(value: ResearchItemResponse) -> int:
    return len(
        json.dumps(
            normalize_json_value(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )


def test_annotation_resource_preview_omits_complete_discussion() -> None:
    thread_id = uuid4()
    comment = AnnotationCommentResponse(
        id=uuid4(),
        thread_id=thread_id,
        content=HOSTILE,
        role="user",
        created_by=ResearchCreatorResponse(id=1, display_name=HOSTILE),
        created_at=NOW,
        updated_at=NOW,
        can_edit=True,
        can_delete=True,
    )
    value = _item(
        kind=ResearchItemKind.ANNOTATION_THREAD,
        annotation_thread=AnnotationThreadContent(
            quote_text=HOSTILE,
            position=None,
            color=AnnotationColor.YELLOW,
            role="user",
            mode=AnnotationThreadMode.HIGHLIGHT,
            comment_count=100,
            last_activity_at=NOW,
            status=AnnotationThreadStatus.OPEN,
            resolved_by=None,
            resolved_at=None,
            capabilities=AnnotationThreadCapabilities(
                reply=True,
                recolor=True,
                resolve=True,
                reopen=False,
                delete=True,
            ),
            comments=[comment] * 100,
        ),
    )

    projected = project_research_item_preview(value)

    assert projected.content_truncated is True
    assert projected.value.annotation_thread is not None
    assert projected.value.annotation_thread.comments == []
    assert _wire_bytes(projected.value) < 16_000


@pytest.mark.parametrize("kind", ["citation", "audio", "data_table"])
def test_research_output_resource_previews_are_json_byte_bounded(kind: str) -> None:
    if kind == "citation":
        value = _item(
            kind=ResearchItemKind.CITATION,
            citation=CitationContent(
                snapshot=CitationSnapshot(
                    kind="citation",
                    document_id=str(uuid4()),
                    preferred_style=HOSTILE[:100],
                    style_display=HOSTILE[:200],
                    data=CitationData(
                        document_id=HOSTILE,
                        title=HOSTILE,
                        authors=[HOSTILE] * 100,
                        journal=HOSTILE,
                        publisher=HOSTILE,
                        doi=HOSTILE,
                    ),
                    method="cached",
                    missing_fields=[HOSTILE] * 100,
                )
            ),
        )
    elif kind == "audio":
        value = _item(
            kind=ResearchItemKind.AUDIO_OVERVIEW,
            audio_overview=AudioOverviewContent(
                title=HOSTILE,
                transcript=HOSTILE,
                citations=[
                    ResponseCitation(text=HOSTILE, index=index, document_id=HOSTILE)
                    for index in range(100)
                ],
                audio_url=HOSTILE,
                voice_id=HOSTILE,
                model_version=HOSTILE,
            ),
        )
    else:
        value = _item(
            kind=ResearchItemKind.DATA_TABLE,
            data_table=DataTableContent(
                title=HOSTILE,
                columns=[HOSTILE] * 100,
                rows=[{"hostile": HOSTILE}] * 1_000,
                citations=[{"hostile": HOSTILE}] * 1_000,
                row_failures=[HOSTILE] * 100,
            ),
        )

    projected = project_research_item_preview(value)

    assert projected.content_truncated is True
    assert _wire_bytes(projected.value) < 32_000
