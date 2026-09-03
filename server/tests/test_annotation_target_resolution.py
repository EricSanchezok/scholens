import pytest
from uuid import uuid4

from app.shared.domain import AppError
from app.tooling.annotation_target_resolution import resolve_annotation_quote
from app.tooling.workspace_contracts import AnnotatePaperInput


def test_agent_annotation_input_defaults_to_personal_and_yellow() -> None:
    request = AnnotatePaperInput(document_id=uuid4(), quote_text="evidence")

    assert request.audience.kind == "personal"
    assert request.color.value == "yellow"


def test_resolves_normalized_quote_to_canonical_offsets() -> None:
    content = "A fine-grained\ncontrol matters more than visuals."
    result = resolve_annotation_quote(
        content=content,
        quote_text="fine-grained control matters more than visuals.",
    )

    assert content[result.start_offset : result.end_offset] == (
        "fine-grained\ncontrol matters more than visuals."
    )


def test_rejects_ambiguous_short_quote_with_candidate_offsets() -> None:
    with pytest.raises(AppError) as error:
        resolve_annotation_quote(content="same text; same text", quote_text="same text")

    assert error.value.code == "annotation_quote_ambiguous"
    assert error.value.details["candidate_count"] == 2


def test_returns_actionable_not_found_error() -> None:
    with pytest.raises(AppError) as error:
        resolve_annotation_quote(content="paper content", quote_text="missing")

    assert error.value.code == "annotation_quote_not_found"
    assert error.value.details["quote_chars"] == 7
