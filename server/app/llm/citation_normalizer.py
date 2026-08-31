"""Single boundary for turning provider attribution into Scholens citations.

The model/provider side may use markers, structured quote attributions, or a
native metadata shape.  This module deliberately keeps those representations
out of the answer and persistence layers: every path is normalized against the
server-owned source registry and then parsed by the same grounded-answer
sanitizer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.llm.citation_adapters import (
    CitationProviderAdapter,
    NormalizedAttribution,
    citation_adapter_for,
)
from app.llm.grounded_answer import GroundedAnswerInspection, inspect_grounded_answer
from app.llm.posthoc_citation import (
    CitationVerifier,
    PosthocCitationResult,
    recover_posthoc_citations,
)
from app.llm.answer_packet import SourceRegistry
from app.modules.conversations.application.contracts.answer_packet import AnswerSource


@dataclass(frozen=True, slots=True)
class CitationNormalizationResult:
    inspection: GroundedAnswerInspection
    provider_attributions: tuple[NormalizedAttribution, ...] = ()


class CitationNormalizer:
    """Normalize all citation representations through one server boundary."""

    def __init__(
        self,
        *,
        provider: str,
        adapter: CitationProviderAdapter | None = None,
        verifier: CitationVerifier | None = None,
    ) -> None:
        self.provider = provider
        self.adapter = adapter or citation_adapter_for(provider)
        self.verifier = verifier

    def normalize(
        self,
        answer: str,
        sources: Sequence[AnswerSource],
        *,
        nonce: str,
        attributions: Sequence[object] = (),
        provider_response: object | None = None,
    ) -> CitationNormalizationResult:
        """Return one sanitized inspection for marker and native metadata paths."""
        registry = SourceRegistry.from_admitted_sources(sources)
        normalized: list[NormalizedAttribution] = []
        if provider_response is not None:
            normalized.extend(
                self.adapter.normalize(
                    provider_response,
                    registry,
                    generated_text=answer,
                )
            )
        structured = [self._attribution_mapping(item) for item in attributions]
        structured = [item for item in structured if item is not None]
        if structured:
            normalized.extend(
                self.adapter.normalize(
                    {"attributions": structured},
                    registry,
                    generated_text=answer,
                )
            )
        deduplicated = tuple(
            dict.fromkeys((item.quote, item.source_keys) for item in normalized)
        )
        provider_attributions = tuple(
            NormalizedAttribution(quote=quote, source_keys=source_keys)
            for quote, source_keys in deduplicated
        )
        inspection = inspect_grounded_answer(
            answer,
            sources,
            nonce=nonce,
            attributions=provider_attributions or attributions,
        )
        return CitationNormalizationResult(
            inspection=inspection,
            provider_attributions=provider_attributions,
        )

    def posthoc(
        self,
        inspection: GroundedAnswerInspection,
        sources: Sequence[AnswerSource],
        *,
        budget_seconds: float = 2.0,
    ) -> PosthocCitationResult:
        """Run the bounded fallback verifier for a citation-free inspection."""
        return recover_posthoc_citations(
            inspection,
            sources,
            budget_seconds=budget_seconds,
            verifier=self.verifier,
        )

    @staticmethod
    def _attribution_mapping(value: object) -> Mapping[str, object] | None:
        if isinstance(value, Mapping):
            return value
        quote = getattr(value, "quote", None)
        source_keys = getattr(value, "source_keys", None)
        if isinstance(quote, str) and isinstance(source_keys, Sequence):
            return {"quote": quote, "source_keys": source_keys}
        return None


__all__ = ["CitationNormalizationResult", "CitationNormalizer"]
