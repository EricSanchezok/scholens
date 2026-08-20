from __future__ import annotations

from scholens_ai import embed_text, semantic_document_text, semantic_source_digest


class _Embedder:
    revision = "test"

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


def test_semantic_document_text_is_stable_and_priority_ordered() -> None:
    text = semantic_document_text(
        title="Code world model",
        keywords=["execution", "reasoning"],
        summary="Learns program behavior.",
        abstract="Uses execution traces as grounded supervision.",
    )

    assert text == (
        "Code world model\n\nexecution · reasoning\n\n"
        "Learns program behavior.\n\n"
        "Uses execution traces as grounded supervision."
    )
    assert semantic_source_digest(text) == semantic_source_digest(text)
    assert len(semantic_source_digest(text)) == 64


def test_embed_text_preserves_query_and_passage_roles() -> None:
    embedder = _Embedder()

    assert embed_text("query", kind="query", embedder=embedder) == [5.0]
    assert embed_text("passage", kind="passage", embedder=embedder) == [7.0]
