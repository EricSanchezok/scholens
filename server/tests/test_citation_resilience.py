from __future__ import annotations

import random
from uuid import uuid4

import pytest
from app.llm.citation_adapters import (
    AnthropicCitationAdapter,
    BedrockCitationAdapter,
    GoogleCitationAdapter,
    OpenAICitationAdapter,
)
from app.llm.citation_normalizer import CitationNormalizer
from app.llm.grounded_answer import inspect_grounded_answer
from app.llm.posthoc_citation import recover_posthoc_citations
from app.modules.conversations.application.contracts.answer_packet import (
    DocumentAnswerSource,
    ExternalAnswerSource,
)
from app.llm.answer_packet import SourceRegistry


def _source(*, key: int = 1, reference: str = "Validated evidence in the paper."):
    return DocumentAnswerSource(
        key=key,
        document_id=uuid4(),
        title="Paper",
        reference=reference,
    )


def test_structured_attributions_are_normalized_against_visible_text() -> None:
    source = _source()
    inspection = inspect_grounded_answer(
        "Validated evidence in the paper.",
        [source],
        nonce="fixed",
        attributions=[
            type(
                "Attribution",
                (),
                {"quote": "Validated evidence in the paper.", "source_keys": [1]},
            )()
        ],
    )
    assert inspection.references is not None
    assert inspection.references.annotations[0].start_offset == 0
    assert inspection.metrics.protocol_errors == 0


def test_citation_normalizer_is_the_single_provider_to_server_boundary() -> None:
    source = _source(reference="A normalized answer.")
    normalized = CitationNormalizer(provider="deepseek").normalize(
        "A normalized answer.",
        [source],
        nonce="fixed",
        attributions=[
            type(
                "Attribution",
                (),
                {"quote": "A normalized answer.", "source_keys": [1]},
            )()
        ],
    )
    assert normalized.provider_attributions[0].source_keys == (1,)
    assert normalized.inspection.references is not None


def test_ambiguous_structured_quote_is_dropped_without_losing_text() -> None:
    source = _source(reference="Evidence")
    inspection = inspect_grounded_answer(
        "Evidence and Evidence",
        [source],
        nonce="fixed",
        attributions=[
            type("Attribution", (), {"quote": "Evidence", "source_keys": [1]})()
        ],
    )
    assert inspection.visible_content == "Evidence and Evidence"
    assert inspection.references is None
    assert inspection.metrics.protocol_errors == 1


def test_duplicate_attributions_merge_and_overlapping_attributions_are_dropped() -> (
    None
):
    source = _source(reference="Evidence supports the result.")
    inspection = inspect_grounded_answer(
        "Evidence supports the result.",
        [source],
        nonce="fixed",
        attributions=[
            type(
                "Attribution",
                (),
                {"quote": "Evidence supports", "source_keys": [1]},
            )(),
            type(
                "Attribution",
                (),
                {"quote": "Evidence supports", "source_keys": [1]},
            )(),
            type(
                "Attribution",
                (),
                {"quote": "supports the result", "source_keys": [1]},
            )(),
        ],
    )
    assert inspection.references is not None
    assert len(inspection.references.annotations) == 1
    assert inspection.metrics.protocol_errors == 1


def test_structured_quote_normalization_preserves_compatibility_character_span() -> (
    None
):
    source = _source(reference="office")
    inspection = inspect_grounded_answer(
        "oﬃce",
        [source],
        nonce="fixed",
        attributions=[
            type("Attribution", (), {"quote": "office", "source_keys": [1]})()
        ],
    )
    assert inspection.references is not None
    assert inspection.references.annotations[0].start_offset == 0
    assert inspection.references.annotations[0].end_offset == len("oﬃce")


def test_structured_quote_allows_unique_english_casefold_but_not_cjk_fuzzy_match() -> (
    None
):
    source = _source(reference="Evidence")
    english = inspect_grounded_answer(
        "evidence",
        [source],
        nonce="fixed",
        attributions=[
            type("Attribution", (), {"quote": "Evidence", "source_keys": [1]})()
        ],
    )
    assert english.references is not None

    cjk = inspect_grounded_answer(
        "证据",
        [_source(reference="證據")],
        nonce="fixed",
        attributions=[type("Attribution", (), {"quote": "證據", "source_keys": [1]})()],
    )
    assert cjk.references is None
    assert cjk.metrics.protocol_errors == 1


def test_posthoc_recovery_is_conservative_and_bounded() -> None:
    source = _source(reference="The result is statistically significant.")
    inspection = inspect_grounded_answer(
        "The result is statistically significant.",
        [source],
        nonce="fixed",
    )
    recovered = recover_posthoc_citations(inspection, [source])
    assert recovered.inspection.references is not None
    assert recovered.inspection.references.sources[0].key == 1
    assert recovered.unverified_claims == 0
    assert recovered.inspection.grounding_status == "verified"


def test_posthoc_recovery_handles_adjacent_cjk_sentence_boundaries() -> None:
    source = _source(reference="压缩方法显著降低推理成本。")
    inspection = inspect_grounded_answer(
        "压缩方法显著降低推理成本。另一个结论暂未验证。",
        [source],
        nonce="fixed",
    )
    recovered = recover_posthoc_citations(inspection, [source])
    assert recovered.inspection.references is not None
    assert recovered.inspection.references.annotations[0].start_offset == 0
    assert recovered.unverified_claims == 1
    assert recovered.inspection.grounding_status == "mixed"


def test_posthoc_verifier_only_runs_for_uncertain_candidates() -> None:
    source = _source(reference="source excerpt without the exact claim")
    inspection = inspect_grounded_answer(
        "The claim is supported.",
        [source],
        nonce="fixed",
    )
    calls: list[tuple[str, str]] = []

    def verifier(claim: str, evidence: str) -> str:
        calls.append((claim, evidence))
        return "SUPPORTED"

    recovered = recover_posthoc_citations(
        inspection,
        [source],
        verifier=verifier,
    )
    assert recovered.inspection.references is not None
    assert len(calls) == 1


def test_posthoc_timeout_keeps_visible_answer_without_citation() -> None:
    source = _source(reference="unrelated evidence")
    inspection = inspect_grounded_answer(
        "A claim that needs verification.",
        [source],
        nonce="fixed",
    )
    recovered = recover_posthoc_citations(
        inspection,
        [source],
        budget_seconds=0,
    )
    assert recovered.timed_out is True
    assert recovered.inspection.visible_content == "A claim that needs verification."


def test_corrupted_marker_fuzz_never_leaks_private_protocol() -> None:
    rng = random.Random(20260831)
    fragments = [
        "[SCHOLENS_CITE:",
        "[[SCHOLENS_CITE:",
        "[SCHOLENS_CITE:stale:",
        "[[SCHOLENS_CITE:fixed:",
        "]",
        "]]",
        ",x]]",
        "999999]]",
    ]
    for _ in range(100):
        value = "Safe answer " + "".join(rng.choice(fragments) for _ in range(3))
        inspection = inspect_grounded_answer(value, [], nonce="fixed")
        assert "SCHOLENS_CITE" not in inspection.visible_content
        assert inspection.visible_content.startswith("Safe answer")


def test_provider_adapters_drop_unknown_sources_without_failing() -> None:
    source = _source(reference="Evidence")
    registry = SourceRegistry()
    registry._sources.append(source)  # noqa: SLF001 - fixture-only registry
    openai = OpenAICitationAdapter().normalize(
        {
            "output_text_annotations": [
                {
                    "start_index": 0,
                    "end_index": 8,
                    "file_citation": {"file_id": "unknown"},
                }
            ]
        },
        registry,
        generated_text="Evidence",
    )
    assert openai == ()
    google = GoogleCitationAdapter().normalize(
        {
            "groundingSupports": [
                {
                    "segment": {"startIndex": 0, "endIndex": 8},
                    "groundingChunkIndices": [0],
                }
            ],
            "groundingChunks": [{"web": {"uri": "unknown"}}],
        },
        registry,
        generated_text="Evidence",
    )
    assert google == ()
    bedrock = BedrockCitationAdapter().normalize(
        {
            "citations": [
                {
                    "generatedResponsePart": {"text": {"text": "Evidence"}},
                    "retrievedReferences": [{"location": {"uri": "unknown"}}],
                }
            ]
        },
        registry,
    )
    assert bedrock == ()


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 8), (0, 0), (8, 0), (0, 9), (True, 8)],
)
def test_provider_adapters_reject_invalid_generated_text_spans(
    start: object,
    end: object,
) -> None:
    source = _source(reference="Evidence")
    registry = SourceRegistry.from_admitted_sources([source])

    openai = OpenAICitationAdapter().normalize(
        {
            "output_text_annotations": [
                {
                    "start_index": start,
                    "end_index": end,
                    "file_citation": {"file_id": str(source.document_id)},
                }
            ]
        },
        registry,
        generated_text="Evidence",
    )
    google = GoogleCitationAdapter().normalize(
        {
            "groundingSupports": [
                {
                    "segment": {"startIndex": start, "endIndex": end},
                    "groundingChunkIndices": [0],
                }
            ],
            "groundingChunks": [{"web": {"uri": source.reference}}],
        },
        registry,
        generated_text="Evidence",
    )

    assert openai == ()
    assert google == ()


def test_provider_adapters_map_native_identifiers_to_admitted_keys() -> None:
    document = _source(reference="OpenAI evidence")
    external = ExternalAnswerSource(
        key=2,
        url="https://example.com/gemini",
        title="Gemini source",
        reference="Gemini evidence",
    )
    registry = SourceRegistry.from_admitted_sources([document, external])

    openai = OpenAICitationAdapter().normalize(
        {
            "output_text_annotations": [
                {
                    "start_index": 0,
                    "end_index": len("OpenAI evidence"),
                    "file_citation": {"file_id": str(document.document_id)},
                }
            ]
        },
        registry,
        generated_text="OpenAI evidence",
    )
    assert openai[0].source_keys == (1,)

    google = GoogleCitationAdapter().normalize(
        {
            "groundingSupports": [
                {
                    "segment": {"startIndex": 0, "endIndex": len("Gemini evidence")},
                    "groundingChunkIndices": [0],
                }
            ],
            "groundingChunks": [{"web": {"uri": "https://example.com/gemini"}}],
        },
        registry,
        generated_text="Gemini evidence",
    )
    assert google[0].source_keys == (2,)

    anthropic = AnthropicCitationAdapter().normalize(
        {
            "content": [
                {
                    "type": "citation",
                    "cited_text": "OpenAI evidence",
                    "document_id": str(document.document_id),
                }
            ]
        },
        registry,
    )
    assert anthropic[0].source_keys == (1,)

    bedrock = BedrockCitationAdapter().normalize(
        {
            "citations": [
                {
                    "generatedResponsePart": {"text": {"text": "OpenAI evidence"}},
                    "retrievedReferences": [{"location": {"uri": document.reference}}],
                }
            ]
        },
        registry,
    )
    assert bedrock[0].source_keys == (1,)
