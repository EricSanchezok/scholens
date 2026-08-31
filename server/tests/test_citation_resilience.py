from __future__ import annotations

from uuid import uuid4

from app.llm.citation_adapters import (
    BedrockCitationAdapter,
    GoogleCitationAdapter,
    OpenAICitationAdapter,
)
from app.llm.grounded_answer import inspect_grounded_answer
from app.llm.posthoc_citation import recover_posthoc_citations
from app.modules.conversations.application.contracts.answer_packet import (
    DocumentAnswerSource,
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
