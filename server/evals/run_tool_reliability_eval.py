"""Grade three-run staging observations against the tool reliability manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVALS_DIR / "tool_reliability_eval_manifest.json"


def _ratio(values: list[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(
    observations_path: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in manifest["cases"]}
    raw_observations = json.loads(observations_path.read_text(encoding="utf-8"))
    observations = (
        raw_observations.get("runs")
        if isinstance(raw_observations, dict)
        else raw_observations
    )
    if not isinstance(observations, list):
        raise ValueError("observations must be a JSON list or an object with runs")

    seen: set[tuple[str, int]] = set()
    task_success: list[bool] = []
    schema_valid: list[bool] = []
    retrieval_hits: list[bool] = []
    source_admission: list[bool] = []
    unauthorized_calls = 0
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError("each observation must be an object")
        case_id = str(observation.get("case_id", ""))
        case = cases.get(case_id)
        run = observation.get("run")
        if case is None or not isinstance(run, int) or run not in {1, 2, 3}:
            raise ValueError(f"invalid case or run: {case_id!r}/{run!r}")
        key = (case_id, run)
        if key in seen:
            raise ValueError(f"duplicate observation: {case_id}/{run}")
        seen.add(key)
        selected = observation.get("selected_tools")
        if not isinstance(selected, list) or not all(
            isinstance(tool, str) for tool in selected
        ):
            raise ValueError(f"{case_id}/{run}: selected_tools must be strings")
        selected_tools = set(selected)
        route_correct = set(case["expected_tools"]) <= selected_tools and set(
            case["forbidden_tools"]
        ).isdisjoint(selected_tools)
        task_success.append(bool(observation.get("task_success")) and route_correct)
        schema_valid.append(bool(observation.get("schema_valid_after_one_retry")))
        unauthorized = observation.get("unauthorized_calls", 0)
        if not isinstance(unauthorized, int) or unauthorized < 0:
            raise ValueError(
                f"{case_id}/{run}: unauthorized_calls must be non-negative"
            )
        unauthorized_calls += unauthorized
        if case["category"] == "retrieval":
            retrieval_hits.append(bool(observation.get("retrieval_hit_at_5")))
        if case["category"] == "citation":
            source_admission.append(bool(observation.get("source_admission_correct")))

    expected = {(case_id, run) for case_id in cases for run in (1, 2, 3)}
    missing = sorted(expected - seen)
    extra = sorted(seen - expected)
    if missing or extra:
        raise ValueError(
            f"observations must contain exactly three runs per case; "
            f"missing={missing[:5]!r}, extra={extra[:5]!r}"
        )

    metrics = {
        "task_success": _ratio(task_success),
        "schema_valid_after_one_retry": _ratio(schema_valid),
        "retrieval_recall_at_5": _ratio(retrieval_hits),
        "source_admission": _ratio(source_admission),
        "unauthorized_calls": unauthorized_calls,
    }
    thresholds = manifest["thresholds"]
    passed = all(
        metrics[name] >= float(thresholds[name])
        for name in (
            "task_success",
            "schema_valid_after_one_retry",
            "retrieval_recall_at_5",
            "source_admission",
        )
    ) and metrics["unauthorized_calls"] <= int(thresholds["unauthorized_calls"])
    return {
        "passed": passed,
        "case_count": len(cases),
        "run_count": len(observations),
        "metrics": metrics,
        "thresholds": thresholds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    result = evaluate(args.observations, manifest_path=args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
