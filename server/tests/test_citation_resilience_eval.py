from __future__ import annotations

from evals.run_citation_resilience_eval import evaluate


def test_redacted_citation_resilience_acceptance_set() -> None:
    result = evaluate()

    assert result["case_count"] == 5
    assert result["structural_precision"] == 1.0
    assert 0 < result["citation_coverage"] < 1
