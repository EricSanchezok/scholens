"""Bounded, deterministic post-hoc citation recovery.

This is deliberately conservative: source similarity is used only to choose
three candidates, while an attribution is emitted only when the complete claim
or source excerpt is contained in the other side after Unicode/whitespace
normalization.  Semantic verification can be added behind the callback without
changing the public response contract.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import monotonic
from typing import Literal, Protocol

from app.modules.conversations.application.contracts.answer_packet import (
    AnswerSource,
    CitationAnnotation,
    ReferenceBundle,
)
from app.llm.grounded_answer import GroundedAnswerInspection

_MAX_CLAIMS = 24
_MAX_CANDIDATES = 3
_BUDGET_SECONDS = 2.0
_CODE_OR_FORMULA = re.compile(r"^\s*(?:```|~~~|\$\$|\\\[|<code>)")
_LINK_ONLY = re.compile(r"^\s*(?:https?://|www\.|\[[^\]]+\]\([^)]*\)\s*$)")
_CLAIM_BOUNDARY = re.compile(r"[。！？.!?]+(?:\s+|(?=\S)|$)|\n{2,}")

VerifierDecision = Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNKNOWN"]


class CitationVerifier(Protocol):
    def __call__(self, claim: str, evidence: str) -> VerifierDecision: ...


@dataclass(frozen=True, slots=True)
class PosthocCitationResult:
    inspection: GroundedAnswerInspection
    checked_claims: int
    unverified_claims: int
    timed_out: bool
    verified_claims: int = 0


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _claims(value: str) -> list[tuple[str, int, int]]:
    claims: list[tuple[str, int, int]] = []
    start = 0
    for match in _CLAIM_BOUNDARY.finditer(value):
        # Keep sentence punctuation in the claim so the annotation covers the
        # same visible span a user reads. Paragraph breaks are separators only.
        end = match.start() if match.group().startswith("\n") else match.end()
        claim = value[start:end].strip()
        if claim and not _CODE_OR_FORMULA.match(claim) and not _LINK_ONLY.match(claim):
            offset = value.find(claim, start, end + 1)
            claims.append(
                (
                    claim,
                    offset if offset >= 0 else start,
                    (offset if offset >= 0 else start) + len(claim),
                )
            )
        start = match.end()
        if len(claims) >= _MAX_CLAIMS:
            return claims
    claim = value[start:].strip()
    if (
        claim
        and not _CODE_OR_FORMULA.match(claim)
        and not _LINK_ONLY.match(claim)
        and len(claims) < _MAX_CLAIMS
    ):
        offset = value.find(claim, start)
        claims.append(
            (
                claim,
                offset if offset >= 0 else start,
                (offset if offset >= 0 else start) + len(claim),
            )
        )
    return claims


def recover_posthoc_citations(
    inspection: GroundedAnswerInspection,
    sources: Sequence[AnswerSource],
    *,
    budget_seconds: float = _BUDGET_SECONDS,
    verifier: CitationVerifier | None = None,
) -> PosthocCitationResult:
    if not sources or not inspection.visible_content.strip():
        return PosthocCitationResult(inspection, 0, 0, False)
    started = monotonic()
    annotations = list(
        inspection.references.annotations if inspection.references else ()
    )
    used_keys = [key for annotation in annotations for key in annotation.source_keys]
    by_key = {source.key: source for source in sources}
    checked = 0
    unverified = 0
    verified = 0
    for claim, start, end in _claims(inspection.visible_content):
        if monotonic() - started > budget_seconds:
            result_inspection = _with_annotations(inspection, annotations, by_key)
            return PosthocCitationResult(
                replace(
                    result_inspection,
                    grounding_status=_grounding_status(
                        inspection.grounding_status,
                        verified,
                        unverified + 1,
                    ),
                ),
                checked,
                unverified + 1,
                True,
                verified,
            )
        checked += 1
        normalized_claim = _normalize(claim)
        candidates = sorted(
            sources,
            key=lambda source: _overlap(normalized_claim, _normalize(source.reference)),
            reverse=True,
        )[:_MAX_CANDIDATES]
        supported = next(
            (
                source
                for source in candidates
                if _contains_evidence(normalized_claim, _normalize(source.reference))
            ),
            None,
        )
        if supported is None and verifier is not None:
            for source in candidates:
                if monotonic() - started > budget_seconds:
                    result_inspection = _with_annotations(
                        inspection, annotations, by_key
                    )
                    return PosthocCitationResult(
                        replace(
                            result_inspection,
                            grounding_status=_grounding_status(
                                inspection.grounding_status,
                                verified,
                                unverified + 1,
                            ),
                        ),
                        checked,
                        unverified + 1,
                        True,
                        verified,
                    )
                try:
                    decision = verifier(claim, source.reference)
                except Exception:
                    decision = "UNKNOWN"
                if decision == "SUPPORTED":
                    supported = source
                    break
        if supported is None:
            unverified += 1
            continue
        verified += 1
        if supported.key in used_keys:
            continue
        annotations.append(
            CitationAnnotation(
                start_offset=start,
                end_offset=end,
                source_keys=[supported.key],
            )
        )
        used_keys.append(supported.key)
    result_inspection = _with_annotations(inspection, annotations, by_key)
    return PosthocCitationResult(
        replace(
            result_inspection,
            grounding_status=_grounding_status(
                inspection.grounding_status,
                verified,
                unverified,
            ),
        ),
        checked,
        unverified,
        False,
        verified,
    )


def _grounding_status(
    existing: Literal["not_evaluated", "verified", "mixed", "unverified"],
    verified: int,
    unverified: int,
) -> Literal["not_evaluated", "verified", "mixed", "unverified"]:
    if existing != "not_evaluated":
        return existing
    if verified and unverified:
        return "mixed"
    if verified:
        return "verified"
    if unverified:
        return "unverified"
    return existing


def _overlap(left: str, right: str) -> int:
    left_words = set(left.split())
    right_words = set(right.split())
    return len(left_words & right_words)


def _contains_evidence(claim: str, evidence: str) -> bool:
    return bool(claim and evidence and (claim in evidence or evidence in claim))


def _with_annotations(
    inspection: GroundedAnswerInspection,
    annotations: list[CitationAnnotation],
    by_key: dict[int, AnswerSource],
) -> GroundedAnswerInspection:
    if not annotations:
        return inspection
    ordered_keys: list[int] = []
    for annotation in annotations:
        for key in annotation.source_keys:
            if key in by_key and key not in ordered_keys:
                ordered_keys.append(key)
    remap = {old: new for new, old in enumerate(ordered_keys, start=1)}
    mapped_annotations = [
        annotation.model_copy(
            update={"source_keys": [remap[key] for key in annotation.source_keys]}
        )
        for annotation in annotations
        if all(key in remap for key in annotation.source_keys)
    ]
    references = ReferenceBundle(
        annotations=mapped_annotations,
        sources=[
            by_key[key].model_copy(update={"key": remap[key]}) for key in ordered_keys
        ],
    )
    metrics = replace(
        inspection.metrics,
        annotations_emitted=len(mapped_annotations),
        unverified_claim_count=inspection.metrics.unverified_claim_count,
    )
    return replace(
        inspection,
        references=references,
        cited_source_keys=frozenset(ordered_keys),
        metrics=metrics,
    )


__all__ = [
    "CitationVerifier",
    "PosthocCitationResult",
    "VerifierDecision",
    "recover_posthoc_citations",
]
