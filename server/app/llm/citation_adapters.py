"""Provider citation metadata adapters.

Providers expose attribution metadata in incompatible shapes.  This module
keeps that translation at the provider boundary and returns only Scholens
``quote``/``source_keys`` pairs; the answer packet remains the source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.llm.answer_packet import SourceRegistry


@dataclass(frozen=True, slots=True)
class NormalizedAttribution:
    quote: str
    source_keys: tuple[int, ...]


class CitationProviderAdapter(Protocol):
    provider: str

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]: ...


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _source_key(registry: SourceRegistry, identifier: object) -> int | None:
    """Map native IDs/URLs to a server-owned key, never inventing one."""
    if isinstance(identifier, int):
        return next(
            (source.key for source in registry.sources if source.key == identifier),
            None,
        )
    value = _text(identifier)
    if value is None:
        return None
    for source in registry.sources:
        if str(getattr(source, "document_id", "")) == value:
            return source.key
        if str(getattr(source, "url", "")) == value:
            return source.key
        if str(getattr(source, "reference", "")) == value:
            return source.key
    return None


def _attribution(
    quote: object,
    identifiers: Sequence[object],
    registry: SourceRegistry,
) -> NormalizedAttribution | None:
    value = _text(quote)
    keys = tuple(
        dict.fromkeys(
            key
            for identifier in identifiers
            if (key := _source_key(registry, identifier)) is not None
        )
    )
    if value is None or not keys:
        return None
    return NormalizedAttribution(quote=value[:4_000], source_keys=keys[:16])


class DeepSeekCitationAdapter:
    provider = "deepseek"

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]:
        payload = _mapping(provider_response)
        values = payload.get("attributions", ()) if payload else ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return ()
        result: list[NormalizedAttribution] = []
        for item in values:
            data = _mapping(item)
            if not data:
                continue
            source_keys = data.get("source_keys", ())
            if not isinstance(source_keys, Sequence) or isinstance(
                source_keys, (str, bytes)
            ):
                continue
            normalized = _attribution(data.get("quote"), source_keys, source_registry)
            if normalized is not None:
                result.append(normalized)
        return tuple(result[:32])


class OpenAICitationAdapter:
    provider = "openai"

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]:
        payload = _mapping(provider_response)
        annotations = payload.get("output_text_annotations", ()) if payload else ()
        if not annotations and payload:
            annotations = payload.get("annotations", ())
            if not annotations:
                output = payload.get("output", ())
                if isinstance(output, Sequence) and not isinstance(
                    output, (str, bytes)
                ):
                    collected: list[object] = []
                    for message in output:
                        message_data = _mapping(message)
                        content = (
                            message_data.get("content", ()) if message_data else ()
                        )
                        if isinstance(content, Sequence) and not isinstance(
                            content, (str, bytes)
                        ):
                            for item in content:
                                item_data = _mapping(item)
                                if item_data and isinstance(
                                    item_data.get("annotations"), Sequence
                                ):
                                    collected.extend(item_data["annotations"])
                    annotations = collected
        if not isinstance(annotations, Sequence) or isinstance(
            annotations, (str, bytes)
        ):
            return ()
        result: list[NormalizedAttribution] = []
        for item in annotations:
            data = _mapping(item)
            if not data:
                continue
            start, end = data.get("start_index"), data.get("end_index")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            quote = generated_text[start:end]
            citation = _mapping(data.get("file_citation")) or _mapping(
                data.get("url_citation")
            )
            identifiers = (
                [citation.get("file_id") or citation.get("url")] if citation else []
            )
            normalized = _attribution(quote, identifiers, source_registry)
            if normalized is not None:
                result.append(normalized)
        return tuple(result[:32])


class GoogleCitationAdapter:
    provider = "google"

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]:
        payload = _mapping(provider_response)
        supports = payload.get("groundingSupports", ()) if payload else ()
        chunks = payload.get("groundingChunks", ()) if payload else ()
        if not isinstance(supports, Sequence) or not isinstance(chunks, Sequence):
            return ()
        result: list[NormalizedAttribution] = []
        for item in supports:
            data = _mapping(item)
            segment = _mapping(data.get("segment")) if data else None
            indices = data.get("groundingChunkIndices", ()) if data else ()
            if not segment or not isinstance(indices, Sequence):
                continue
            start, end = segment.get("startIndex", 0), segment.get("endIndex", 0)
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            identifiers: list[object] = []
            for index in indices:
                if isinstance(index, int) and 0 <= index < len(chunks):
                    chunk = _mapping(chunks[index])
                    web = _mapping(chunk.get("web")) if chunk else None
                    identifiers.append(web.get("uri") if web else None)
            normalized = _attribution(
                generated_text[start:end], identifiers, source_registry
            )
            if normalized is not None:
                result.append(normalized)
        return tuple(result[:32])


class AnthropicCitationAdapter:
    provider = "anthropic"

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]:
        payload = _mapping(provider_response)
        blocks = payload.get("content", ()) if payload else ()
        if not isinstance(blocks, Sequence):
            return ()
        result: list[NormalizedAttribution] = []
        for block in blocks:
            data = _mapping(block)
            if not data or data.get("type") not in {"citation", "citations", "text"}:
                continue
            citations = data.get("citations", ())
            if not citations and data.get("type") == "citation":
                citations = [data]
            if not isinstance(citations, Sequence):
                continue
            for citation in citations:
                item = _mapping(citation)
                if not item:
                    continue
                normalized = _attribution(
                    item.get("cited_text") or item.get("text"),
                    [
                        item.get("source"),
                        item.get("document_index"),
                        item.get("document_id"),
                    ],
                    source_registry,
                )
                if normalized is not None:
                    result.append(normalized)
        return tuple(result[:32])


class BedrockCitationAdapter:
    provider = "bedrock"

    def normalize(
        self,
        provider_response: object,
        source_registry: SourceRegistry,
        *,
        generated_text: str = "",
    ) -> tuple[NormalizedAttribution, ...]:
        payload = _mapping(provider_response)
        citations = payload.get("citations", ()) if payload else ()
        if not isinstance(citations, Sequence):
            return ()
        result: list[NormalizedAttribution] = []
        for citation in citations:
            data = _mapping(citation)
            span = _mapping(data.get("generatedResponsePart")) if data else None
            text = _mapping(span.get("text")) if span else None
            refs = data.get("retrievedReferences", ()) if data else ()
            if not text or not isinstance(refs, Sequence):
                continue
            identifiers: list[object] = []
            for reference in refs:
                item = _mapping(reference)
                location = _mapping(item.get("location")) if item else None
                if location:
                    s3_location = _mapping(location.get("s3Location"))
                    identifiers.append(
                        location.get("uri")
                        or (s3_location.get("uri") if s3_location else None)
                    )
            normalized = _attribution(text.get("text"), identifiers, source_registry)
            if normalized is not None:
                result.append(normalized)
        return tuple(result[:32])


_ADAPTERS: dict[str, CitationProviderAdapter] = {
    adapter.provider: adapter
    for adapter in (
        DeepSeekCitationAdapter(),
        OpenAICitationAdapter(),
        GoogleCitationAdapter(),
        AnthropicCitationAdapter(),
        BedrockCitationAdapter(),
    )
}


def citation_adapter_for(provider: str) -> CitationProviderAdapter:
    return _ADAPTERS.get(provider, _ADAPTERS["deepseek"])


__all__ = [
    "AnthropicCitationAdapter",
    "BedrockCitationAdapter",
    "CitationProviderAdapter",
    "DeepSeekCitationAdapter",
    "GoogleCitationAdapter",
    "NormalizedAttribution",
    "OpenAICitationAdapter",
    "citation_adapter_for",
]
