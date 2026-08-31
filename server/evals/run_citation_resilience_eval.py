"""Run the deterministic, offline citation resilience acceptance set.

The manifest contains only redacted prose and source excerpts.  This command
checks the invariants that can be proven without a live provider: safe text is
preserved, unknown/ambiguous metadata is dropped, and every emitted annotation
points to an admitted source.  Semantic precision remains a separate human or
verifier-backed evaluation series.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.llm.citation_normalizer import CitationNormalizer
from app.llm.posthoc_citation import recover_posthoc_citations
from app.modules.conversations.application.contracts.answer_packet import (
    DocumentAnswerSource,
)

EVALS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVALS_DIR / "citation_resilience_eval_manifest.json"


def _sources(case_id: str, references: list[str]) -> list[DocumentAnswerSource]:
    return [
        DocumentAnswerSource(
            key=index,
            document_id=uuid5(
                NAMESPACE_URL, f"scholens-citation-eval:{case_id}:{index}"
            ),
            title=f"Offline citation source {index}",
            reference=reference,
        )
        for index, reference in enumerate(references, start=1)
    ]


def _status(*, sources: list[DocumentAnswerSource], inspection) -> str:
    if not sources:
        return "not_required"
    if inspection.references is None or not inspection.references.annotations:
        return "unavailable"
    if inspection.metrics.invalid_source_keys or inspection.metrics.protocol_errors:
        return "partial"
    return "complete"


def evaluate(manifest_path: Path = MANIFEST_PATH) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text())
    results: list[dict[str, object]] = []
    total_claims = 0
    cited_claims = 0
    valid_annotations = 0
    emitted_annotations = 0
    for case in manifest["cases"]:
        case_id = str(case["id"])
        sources = _sources(case_id, list(case.get("sources", [])))
        normalized = CitationNormalizer(provider="deepseek").normalize(
            str(case["answer"]),
            sources,
            nonce="eval",
            attributions=list(case.get("attributions", [])),
        )
        inspection = normalized.inspection
        if case.get("posthoc"):
            inspection = recover_posthoc_citations(inspection, sources).inspection
        references = inspection.references
        annotations = references.annotations if references is not None else []
        emitted_annotations += len(annotations)
        valid = sum(
            all(key <= len(sources) for key in annotation.source_keys)
            for annotation in annotations
        )
        valid_annotations += valid
        claims = int(case.get("fact_claims", 0))
        total_claims += claims
        cited_claims += min(len(annotations), claims)
        actual_status = _status(sources=sources, inspection=inspection)
        if inspection.visible_content != case["expected_visible"]:
            raise AssertionError(
                f"{case_id}: visible content changed unexpectedly: "
                f"{inspection.visible_content!r}"
            )
        if actual_status != case["expected_status"]:
            raise AssertionError(
                f"{case_id}: expected status {case['expected_status']!r}, "
                f"got {actual_status!r}"
            )
        results.append(
            {
                "id": case_id,
                "kind": case["kind"],
                "status": actual_status,
                "annotations": len(annotations),
                "dropped_annotations": inspection.metrics.dropped_annotation_count,
            }
        )
    return {
        "cases": results,
        "structural_precision": (
            valid_annotations / emitted_annotations if emitted_annotations else 1.0
        ),
        "citation_coverage": cited_claims / total_claims if total_claims else 0.0,
        "case_count": len(results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
