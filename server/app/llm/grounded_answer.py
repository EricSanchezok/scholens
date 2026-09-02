"""Streaming grounded-answer control protocol and citation materialization."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
import unicodedata
import re

from app.modules.conversations.application.contracts.answer_packet import (
    AnswerSource,
    CitationAnnotation,
    MessageReference,
    ReferenceBundle,
)

_CJK_TEXT = re.compile(r"[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def grounded_citation_instructions(nonce: str) -> str:
    """Instructions that remain valid while an agent discovers sources."""

    return (
        "Tool results may include server-validated integer source_keys. When a "
        "factual passage relies on those materials, append exactly one private "
        f"[[SCHOLENS_CITE:{nonce}:1]] marker after the passage, replacing 1 with "
        "every supplied key that supports it. Never cite a key absent from a tool "
        "result or the initial answer packet. Do not invent visible citation labels "
        "such as [A1] or [1], Markdown footnotes, a bibliography, URLs, or document "
        "IDs; the product renders citations from private markers. Never repeat the "
        "private markers as prose. If no validated keys are supplied, do not emit a "
        "citation marker."
    )


@dataclass(frozen=True, slots=True)
class GroundedAnswerMetrics:
    annotations_emitted: int
    invalid_source_keys: int
    protocol_errors: int
    dropped_annotation_count: int = 0
    unverified_claim_count: int = 0


@dataclass(frozen=True, slots=True)
class GroundedAnswerInspection:
    """One completed parse reused by final-answer validation and publication."""

    raw_content: str
    visible_content: str
    cited_source_keys: frozenset[int]
    references: ReferenceBundle | None
    metrics: GroundedAnswerMetrics
    posthoc_timed_out: bool = False
    grounding_status: Literal["not_evaluated", "verified", "mixed", "unverified"] = (
        "not_evaluated"
    )

    @property
    def has_citation_errors(self) -> bool:
        return bool(self.metrics.invalid_source_keys or self.metrics.protocol_errors)

    @property
    def citation_status(
        self,
    ) -> Literal["not_required", "complete", "partial", "unavailable", "pending"]:
        if self.references is None or not self.references.annotations:
            return "unavailable" if self.has_citation_errors else "not_required"
        return "partial" if self.has_citation_errors else "complete"


def inspect_grounded_answer(
    value: str,
    sources: Sequence[AnswerSource],
    *,
    nonce: str,
    attributions: Sequence[object] = (),
) -> GroundedAnswerInspection:
    parser = GroundedAnswerStreamParser(sources, nonce=nonce)
    visible = parser.feed(value) + parser.finish()
    parser.attach_attributions(attributions)
    return GroundedAnswerInspection(
        raw_content=value,
        visible_content=visible,
        cited_source_keys=parser.cited_source_keys(),
        references=parser.references(),
        metrics=parser.metrics(),
    )


class GroundedAnswerStreamParser:
    """Strip private citation markers and map them to preceding text passages."""

    _SINGLE_MARKER_PREFIX = "[SCHOLENS_CITE:"
    _DOUBLE_MARKER_PREFIX = "[[SCHOLENS_CITE:"

    def __init__(
        self, sources: Sequence[AnswerSource], *, nonce: str | None = None
    ) -> None:
        self.nonce = nonce or secrets.token_hex(16)
        self._sources = {source.key: source for source in sources}
        self._buffer = ""
        self._output = ""
        self._paragraph_start = 0
        self._citation_cursor = 0
        self._annotations: list[CitationAnnotation] = []
        self._invalid_source_keys = 0
        self._protocol_errors = 0
        self._finished = False

    def feed(self, value: str) -> str:
        if self._finished:
            raise RuntimeError("grounded answer parser is already finished")
        self._buffer += value
        rendered: list[str] = []
        while self._buffer:
            marker_at, double_bracketed = self._find_marker(self._buffer)
            if marker_at >= 0:
                self._emit(self._buffer[:marker_at], rendered)
                marker_prefix = (
                    self._DOUBLE_MARKER_PREFIX
                    if double_bracketed
                    else self._SINGLE_MARKER_PREFIX
                )
                marker_suffix = "]]" if double_bracketed else "]"
                marker_end = self._buffer.find(
                    marker_suffix,
                    marker_at + len(marker_prefix),
                )
                if marker_end < 0:
                    self._buffer = self._buffer[marker_at:]
                    break
                raw_marker = self._buffer[marker_at : marker_end + len(marker_suffix)]
                self._buffer = self._buffer[marker_end + len(marker_suffix) :]
                valid_marker_prefix = f"{marker_prefix}{self.nonce}:"
                if raw_marker.startswith(valid_marker_prefix):
                    raw_keys = raw_marker[
                        len(valid_marker_prefix) : -len(marker_suffix)
                    ]
                    self._annotate(raw_keys)
                else:
                    # Never leak forged, stale, or model-damaged private protocol
                    # into the visible answer, but never trust it as a citation.
                    self._protocol_errors += 1
                continue

            hold = self._partial_marker_suffix_length(self._buffer)
            ready = self._buffer[:-hold] if hold else self._buffer
            self._buffer = self._buffer[-hold:] if hold else ""
            self._emit(ready, rendered)
            break
        return "".join(rendered)

    def finish(self) -> str:
        if self._finished:
            return ""
        self._finished = True
        remaining = self._buffer
        self._buffer = ""
        if remaining.startswith(
            (self._SINGLE_MARKER_PREFIX, self._DOUBLE_MARKER_PREFIX)
        ):
            remaining = ""
            self._protocol_errors += 1
        else:
            partial = self._partial_marker_suffix_length(remaining)
            if partial:
                remaining = remaining[:-partial]
                self._protocol_errors += 1
        self._append_output(remaining)
        return remaining

    def references(self) -> ReferenceBundle | None:
        if not self._finished:
            raise RuntimeError("finish the grounded answer parser first")
        valid_annotations = self._valid_annotations()
        ordered_keys: list[int] = []
        for annotation in valid_annotations:
            for key in annotation.source_keys:
                if key not in ordered_keys:
                    ordered_keys.append(key)
        if not ordered_keys:
            return None
        remap = {old: new for new, old in enumerate(ordered_keys, start=1)}
        annotations = [
            annotation.model_copy(
                update={"source_keys": [remap[key] for key in annotation.source_keys]}
            )
            for annotation in valid_annotations
        ]
        sources: list[MessageReference] = [
            self._sources[key].model_copy(update={"key": remap[key]})
            for key in ordered_keys
        ]
        return ReferenceBundle(annotations=annotations, sources=sources)

    def cited_source_keys(self) -> frozenset[int]:
        if not self._finished:
            raise RuntimeError("finish the grounded answer parser first")
        return frozenset(
            key
            for annotation in self._valid_annotations()
            for key in annotation.source_keys
        )

    def metrics(self) -> GroundedAnswerMetrics:
        return GroundedAnswerMetrics(
            annotations_emitted=len(self._annotations),
            invalid_source_keys=self._invalid_source_keys,
            protocol_errors=self._protocol_errors,
            dropped_annotation_count=(
                self._invalid_source_keys + self._protocol_errors
            ),
        )

    def attach_attributions(self, attributions: Sequence[object]) -> None:
        """Attach optional structured attributions after marker parsing.

        The model may provide a quote and source keys without knowing offsets.
        Offsets are resolved only against the server-sanitized visible answer;
        an ambiguous or unknown quote is dropped and never makes the answer
        unavailable.
        """
        for attribution in attributions:
            quote = getattr(attribution, "quote", None)
            requested = getattr(attribution, "source_keys", None)
            if not isinstance(quote, str) or not quote.strip():
                self._protocol_errors += 1
                continue
            if not isinstance(requested, Sequence) or isinstance(
                requested, (str, bytes)
            ):
                self._invalid_source_keys += 1
                continue
            try:
                keys = tuple(dict.fromkeys(int(key) for key in requested))
            except (TypeError, ValueError):
                keys = ()
            if not keys or any(key not in self._sources for key in keys):
                self._invalid_source_keys += 1
                continue
            span = _locate_quote(self._output, quote)
            if span is None:
                self._protocol_errors += 1
                continue
            for index, previous in enumerate(self._annotations):
                if previous.start_offset == span[0] and previous.end_offset == span[1]:
                    merged_keys = list(dict.fromkeys([*previous.source_keys, *keys]))
                    self._annotations[index] = previous.model_copy(
                        update={"source_keys": merged_keys}
                    )
                    break
                if max(previous.start_offset, span[0]) < min(
                    previous.end_offset, span[1]
                ):
                    # Overlapping provider spans are ambiguous for inline
                    # rendering. Keep the first deterministic span and drop
                    # the later one without affecting the answer.
                    self._protocol_errors += 1
                    break
            else:
                self._annotations.append(
                    CitationAnnotation(
                        start_offset=span[0],
                        end_offset=span[1],
                        source_keys=list(keys),
                    )
                )

    def _annotate(self, raw_keys: str) -> None:
        try:
            requested = tuple(
                dict.fromkeys(int(item.strip()) for item in raw_keys.split(","))
            )
        except ValueError:
            requested = ()
        if not requested or any(key not in self._sources for key in requested):
            self._invalid_source_keys += 1
            self._citation_cursor = len(self._output)
            return

        start = max(self._citation_cursor, self._paragraph_start)
        end = len(self._output)
        while start < end and self._output[start].isspace():
            start += 1
        while end > start and self._output[end - 1].isspace():
            end -= 1
        self._citation_cursor = len(self._output)
        if start >= end:
            self._protocol_errors += 1
            return

        if self._annotations and self._annotations[-1].end_offset == end:
            previous = self._annotations[-1]
            merged_keys = list(dict.fromkeys([*previous.source_keys, *requested]))
            self._annotations[-1] = previous.model_copy(
                update={"source_keys": merged_keys}
            )
            return
        self._annotations.append(
            CitationAnnotation(
                start_offset=start,
                end_offset=end,
                source_keys=list(requested),
            )
        )

    def _valid_annotations(self) -> list[CitationAnnotation]:
        return [
            annotation
            for annotation in self._annotations
            if 0 <= annotation.start_offset < annotation.end_offset <= len(self._output)
        ]

    def _emit(self, value: str, rendered: list[str]) -> None:
        if not value:
            return
        rendered.append(value)
        self._append_output(value)

    def _append_output(self, value: str) -> None:
        if not value:
            return
        previous_length = len(self._output)
        self._output += value
        boundary = self._output.rfind("\n\n", max(0, previous_length - 1))
        if boundary >= 0:
            self._paragraph_start = boundary + 2

    @staticmethod
    def _partial_suffix_length(value: str, token: str) -> int:
        maximum = min(len(value), len(token) - 1)
        for length in range(maximum, 0, -1):
            if value.endswith(token[:length]):
                return length
        return 0

    @classmethod
    def _partial_marker_suffix_length(cls, value: str) -> int:
        return max(
            cls._partial_suffix_length(value, cls._SINGLE_MARKER_PREFIX),
            cls._partial_suffix_length(value, cls._DOUBLE_MARKER_PREFIX),
        )

    @classmethod
    def _find_marker(cls, value: str) -> tuple[int, bool]:
        single_at = value.find(cls._SINGLE_MARKER_PREFIX)
        double_at = value.find(cls._DOUBLE_MARKER_PREFIX)
        if double_at >= 0 and (single_at < 0 or double_at < single_at):
            return double_at, True
        if single_at >= 0:
            return single_at, False
        return -1, False


def _normalized_with_offsets(
    value: str,
    *,
    casefold: bool = False,
) -> tuple[str, list[int]]:
    """Return normalized text and original character offsets.

    Normalization is performed per original character so compatibility
    expansions and case-fold expansions still map to a safe original span.
    """
    output: list[str] = []
    offsets: list[int] = []
    pending_space = False
    pending_offset = 0
    # Normalize one original character at a time so compatibility expansions
    # (for example, ``ﬀ`` → ``ff``) still point back to a valid source span.
    for index, original_character in enumerate(value):
        for character in unicodedata.normalize("NFKC", original_character):
            if casefold:
                character = character.casefold()
            for folded_character in character:
                if folded_character.isspace():
                    if output:
                        pending_space = True
                        pending_offset = index
                    continue
                if pending_space:
                    output.append(" ")
                    offsets.append(pending_offset)
                    pending_space = False
                output.append(folded_character)
                offsets.append(index)
    return "".join(output), offsets


def _locate_quote(value: str, quote: str) -> tuple[int, int] | None:
    exact = value.find(quote)
    if exact >= 0 and value.find(quote, exact + 1) < 0:
        return exact, exact + len(quote)
    normalized_value, offsets = _normalized_with_offsets(value)
    normalized_quote, _ = _normalized_with_offsets(quote.strip())
    if not normalized_quote:
        return None
    first = normalized_value.find(normalized_quote)
    normalized_span: tuple[int, int] | None = None
    if (
        first >= 0
        and first + len(normalized_quote) <= len(offsets)
        and normalized_value.find(normalized_quote, first + 1) < 0
    ):
        start = offsets[first]
        last = first + len(normalized_quote) - 1
        normalized_span = (start, offsets[last] + 1)
    if normalized_span is not None:
        if _CJK_TEXT.search(value) or _CJK_TEXT.search(quote):
            return normalized_span
    elif _CJK_TEXT.search(value) or _CJK_TEXT.search(quote):
        return None

    # English-only case folding is intentionally a separate, conservative
    # phase. Chinese and other CJK text never enters fuzzy matching.
    folded_value, folded_offsets = _normalized_with_offsets(value, casefold=True)
    folded_quote, _ = _normalized_with_offsets(quote.strip(), casefold=True)
    folded_first = folded_value.find(folded_quote)
    if (
        folded_first < 0
        or folded_first + len(folded_quote) > len(folded_offsets)
        or folded_value.find(folded_quote, folded_first + 1) >= 0
    ):
        return normalized_span
    return (
        folded_offsets[folded_first],
        folded_offsets[folded_first + len(folded_quote) - 1] + 1,
    )
