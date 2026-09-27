"""Verbatim evidence with bounded segments and reversible Unicode normalization.

Normalization preserves case and punctuation. It never repairs, paraphrases or
fuzzily matches text. Returned quotes always come from the unchanged source.
"""

from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import unicodedata

EVIDENCE_REVISION = "ev1"
SEGMENT_CHARACTERS = 2400
SEGMENT_OVERLAP = 400


@dataclass(frozen=True, slots=True)
class EvidenceSegment:
    id: str
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    start: int
    end: int
    quote: str
    digest: str


@dataclass(frozen=True, slots=True)
class EvidenceResolution:
    anchor: EvidenceAnchor | None = None
    reason: str | None = None


def _segment_id(content_digest: str, start: int, end: int) -> str:
    signature = hashlib.sha256(f"{content_digest}:{start}:{end}".encode()).hexdigest()[
        :24
    ]
    return f"{EVIDENCE_REVISION}:{start}:{end}:{signature}"


def evidence_segments(content: str) -> Iterator[EvidenceSegment]:
    content_digest = hashlib.sha256(content.encode()).hexdigest()
    start = 0
    while start < len(content):
        end = min(start + SEGMENT_CHARACTERS, len(content))
        if end < len(content):
            boundary = content.rfind("\n\n", start + SEGMENT_CHARACTERS // 2, end)
            if boundary >= 0:
                end = boundary + 2
        yield EvidenceSegment(
            id=_segment_id(content_digest, start, end),
            start=start,
            end=end,
            text=content[start:end],
        )
        if end == len(content):
            break
        start = end - SEGMENT_OVERLAP


def _normalize(text: str) -> tuple[str, list[tuple[int, int]]]:
    units = list(_normalized_units(text, 0, len(text)))
    return "".join(char for char, _, _ in units), [
        (start, end) for _, start, end in units
    ]


def _normalized_units(
    text: str, start: int, end: int
) -> Iterator[tuple[str, int, int]]:
    whitespace: tuple[int, int] | None = None
    for index in range(start, end):
        # Decomposition makes composed/decomposed accents and PDF ligatures
        # equivalent without losing the original character coordinates.
        for char in unicodedata.normalize("NFKD", text[index]):
            if char.isspace():
                whitespace = (whitespace[0] if whitespace else index, index + 1)
                continue
            if whitespace:
                yield " ", *whitespace
                whitespace = None
            yield char, index, index + 1
    if whitespace:
        yield " ", *whitespace


def _matches(
    content: str, start: int, end: int, needle: str
) -> Iterator[tuple[int, int]]:
    # Legacy unsegmented payloads may cover a 40 MiB source. Normalize bounded
    # blocks with a quote-sized overlap instead of allocating offsets for every
    # character of the entire document for every highlight.
    units: list[tuple[str, int, int]] = []
    previous: tuple[int, int] | None = None

    def find() -> Iterator[tuple[int, int]]:
        normalized = "".join(char for char, _, _ in units)
        found = normalized.find(needle)
        while found >= 0:
            yield units[found][1], units[found + len(needle) - 1][2]
            found = normalized.find(needle, found + 1)

    for unit in _normalized_units(content, start, end):
        units.append(unit)
        if len(units) >= 4096:
            for match in find():
                if match != previous:
                    yield match
                    previous = match
            units = units[-(len(needle) - 1) :]
    for match in find():
        if match != previous:
            yield match
            previous = match


def resolve_evidence(
    content: str,
    quote: str,
    *,
    segment_id: str | None = None,
    content_digest: str | None = None,
) -> EvidenceResolution:
    """Resolve a unique quote; unsegmented legacy results remain exact-only.

    A segment ID binds the complete source digest and its bounds, so an old
    generation cannot silently anchor into modified canonical text.
    """
    if len(quote) > 4096:
        return EvidenceResolution(reason="invalid_quote")
    digest = content_digest or hashlib.sha256(content.encode()).hexdigest()
    start, end = 0, len(content)
    if segment_id is not None:
        try:
            revision, left_text, right_text, _signature = segment_id.split(":")
            start, end = int(left_text), int(right_text)
        except (ValueError, TypeError):
            return EvidenceResolution(reason="invalid_segment")
        if (
            revision != EVIDENCE_REVISION
            or not 0 <= start < end <= len(content)
            or end - start > SEGMENT_CHARACTERS
            or segment_id != _segment_id(digest, start, end)
        ):
            return EvidenceResolution(reason="stale_segment")
    needle, _ = _normalize(quote.strip())
    if not 8 <= len(needle) <= 1200:
        return EvidenceResolution(reason="invalid_quote")
    matches = _matches(content, start, end, needle)
    match = next(matches, None)
    if match is None:
        return EvidenceResolution(reason="not_found")
    if next(matches, None) is not None:
        return EvidenceResolution(reason="ambiguous")
    left, right = match
    original = content[left:right]
    # A quote cannot match only part of a compatibility-expanded character.
    if _normalize(original)[0] != needle:
        return EvidenceResolution(reason="partial_character")
    evidence_digest = hashlib.sha256(
        f"{EVIDENCE_REVISION}:{digest}:{left}:{right}".encode()
    ).hexdigest()
    return EvidenceResolution(
        anchor=EvidenceAnchor(left, right, original, evidence_digest)
    )


__all__ = [
    "EVIDENCE_REVISION",
    "EvidenceAnchor",
    "EvidenceResolution",
    "EvidenceSegment",
    "evidence_segments",
    "resolve_evidence",
]
