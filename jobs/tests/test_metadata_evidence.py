import asyncio
import json
from types import SimpleNamespace

from scholens_ai import resolve_evidence

from src.llm_client import AIExtractionClient
from src.schemas import PaperMetadataExtraction


def test_metadata_prompt_has_complete_bounded_segments_and_verbatim_contract(
    monkeypatch,
):
    client = AIExtractionClient()
    client.profile = SimpleNamespace(max_input_chars=12_000)
    prompts = []

    async def generate(**kwargs):
        prompts.append(kwargs["prompt"])
        return PaperMetadataExtraction(title="Fixture")

    monkeypatch.setattr(client, "_generate_structured", generate)
    content = "The efficient method improved measurable results.\n\n" * 2000
    asyncio.run(client.extract_paper_metadata(content, "fixture"))
    prompt = prompts[0]
    assert len(prompt) <= client.profile.max_input_chars
    assert "Never paraphrase a quote" in prompt
    lines = [
        json.loads(line)
        for line in prompt.splitlines()
        if line.startswith('{"segment_id":')
    ]
    assert lines
    for line in lines:
        result = resolve_evidence(
            content, line["text"][:40], segment_id=line["segment_id"]
        )
        # Repeated synthetic text is deliberately ambiguous, never wrong-anchored.
        assert result.reason == "ambiguous"
