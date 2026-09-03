"""Deterministic, content-addressed resolution for agent-created annotations."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class ResolvedAnnotationTarget:
    start_offset: int
    end_offset: int


def _normalized_with_offsets(value: str) -> tuple[str, list[int], list[int]]:
    normalized: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pending_space = False
    for offset, character in enumerate(value):
        if character == "\u00ad":
            continue
        if character.isspace():
            if normalized and not pending_space:
                normalized.append(" ")
                starts.append(offset)
                ends.append(offset + 1)
            pending_space = True
            continue
        pending_space = False
        folded = unicodedata.normalize("NFKC", character)
        for folded_character in folded:
            normalized.append(folded_character)
            starts.append(offset)
            ends.append(offset + 1)
    if normalized and normalized[-1] == " ":
        normalized.pop()
        starts.pop()
        ends.pop()
    return "".join(normalized), starts, ends


def resolve_annotation_quote(
    *, content: str, quote_text: str
) -> ResolvedAnnotationTarget:
    """Resolve one quote to canonical character offsets without fuzzy writes."""

    if not content:
        raise AppError(
            code="annotation_content_unavailable",
            message=(
                "Paper text is not available for automatic anchoring; wait for "
                "parsing to complete and retry"
            ),
            kind=FailureKind.CONFLICT,
        )
    haystack, starts, ends = _normalized_with_offsets(content)
    needle, _, _ = _normalized_with_offsets(quote_text)
    if not needle:
        raise AppError(
            code="annotation_quote_not_found",
            message="quote_text must contain visible paper text",
            kind=FailureKind.INVALID_ARGUMENT,
        )

    matches: list[int] = []
    cursor = 0
    while True:
        match = haystack.find(needle, cursor)
        if match < 0:
            break
        matches.append(match)
        cursor = match + max(1, len(needle))
        if len(matches) >= 6:
            break
    if not matches:
        raise AppError(
            code="annotation_quote_not_found",
            message=(
                "quote_text was not found in the current paper text after "
                "Unicode and whitespace normalization; provide a longer exact "
                "passage or refresh paper content"
            ),
            kind=FailureKind.INVALID_ARGUMENT,
            details={"quote_chars": len(quote_text)},
        )
    if len(matches) > 1:
        raise AppError(
            code="annotation_quote_ambiguous",
            message=(
                "quote_text occurs more than once; include nearby words so the "
                "annotation has one deterministic anchor"
            ),
            kind=FailureKind.INVALID_ARGUMENT,
            details={
                "candidate_count": len(matches),
                "candidate_offsets": [
                    starts[index] for index in matches[:5] if index < len(starts)
                ],
            },
        )
    match = matches[0]
    end_index = match + len(needle) - 1
    if match >= len(starts) or end_index >= len(ends):
        raise AppError(
            code="annotation_quote_not_found",
            message="quote_text could not be mapped to canonical text offsets",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    return ResolvedAnnotationTarget(
        start_offset=starts[match],
        end_offset=ends[end_index],
    )


__all__ = ["ResolvedAnnotationTarget", "resolve_annotation_quote"]
