import ast
import hashlib
import json
import math
import operator
from pathlib import Path

from evals.run_tool_reliability_eval import evaluate as evaluate_tool_reliability


SERVER_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = SERVER_ROOT / "evals"
SEED_ROOT = EVAL_ROOT / "seed_data"
MANIFEST_PATH = EVAL_ROOT / "data_table_eval_manifest.json"
ATTRIBUTION_PATH = SEED_ROOT / "README.md"
TOOL_RELIABILITY_MANIFEST = EVAL_ROOT / "tool_reliability_eval_manifest.json"
MCP_CONTRACT = SERVER_ROOT / "contracts" / "mcp-v1.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _calculate(expression: str) -> float:
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](visit(node.left), visit(node.right))
        raise AssertionError(f"Unsupported derived formula: {expression}")

    return visit(ast.parse(expression, mode="eval"))


def test_eval_fixtures_match_attribution_and_checksums() -> None:
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    runner_text = (EVAL_ROOT / "run_data_table_eval.py").read_text(encoding="utf-8")
    attribution = ATTRIBUTION_PATH.read_text(encoding="utf-8")
    papers = _manifest()["papers"]

    assert "KHO-" not in manifest_text
    assert "KHO-" not in runner_text
    assert {paper["key"] for paper in papers} == {
        "wei_cot",
        "health_chatbots",
        "coding_course",
    }
    for paper in papers:
        fixture = SEED_ROOT / paper["file"]
        assert fixture.is_file()
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == paper["sha256"]
        assert paper["authors"]
        assert paper["identifier"]
        assert paper["source_url"].startswith("https://")
        assert paper["license"] == "CC BY 4.0"
        assert paper["license_url"] == ("https://creativecommons.org/licenses/by/4.0/")
        assert paper["file"] in attribution
        assert paper["identifier"] in attribution
        assert paper["source_url"] in attribution
        assert paper["sha256"] in attribution

    assert attribution.count("Modification status: unmodified source PDF") == len(
        papers
    )


def test_eval_derived_formulas_match_their_golden_values() -> None:
    for paper in _manifest()["papers"]:
        for column in paper["columns"]:
            if column["kind"] != "derived":
                continue
            assert math.isclose(
                _calculate(column["formula"]),
                column["expected"],
                abs_tol=column["tolerance"],
            )


def test_coding_course_golden_values_are_fixed() -> None:
    paper = next(
        paper for paper in _manifest()["papers"] if paper["key"] == "coding_course"
    )
    primitive = [
        column["expected"]
        for column in paper["columns"]
        if column["kind"] == "primitive"
    ]
    derived = [
        column["expected"] for column in paper["columns"] if column["kind"] == "derived"
    ]

    assert paper["file"] == "human_gpt_coding_course.pdf"
    assert primitive == [71.9, 81.1, 30.9, 48.8, 85.3, 77]
    assert derived == [9.2, 17.9, 13]
    assert [
        column["formula"] for column in paper["columns"] if column["kind"] == "derived"
    ] == ["81.1 - 71.9", "48.8 - 30.9", "90 - 77"]


def test_tool_reliability_manifest_is_redacted_and_balanced() -> None:
    raw = TOOL_RELIABILITY_MANIFEST.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    cases = manifest["cases"]

    assert len(cases) == 32
    assert {
        category: sum(case["category"] == category for case in cases)
        for category in {"route", "retrieval", "recovery", "citation"}
    } == {
        "route": 10,
        "retrieval": 10,
        "recovery": 6,
        "citation": 6,
    }
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["expected_tools"] for case in cases)
    assert all(
        set(case["expected_tools"]).isdisjoint(case["forbidden_tools"])
        for case in cases
    )
    assert "reader_url" not in raw.replace(
        "actual returned Reader URL", "actual returned link"
    )
    assert "@" not in raw
    assert "00000000-" not in raw


def test_tool_reliability_manifest_references_canonical_catalog_tools() -> None:
    manifest = json.loads(TOOL_RELIABILITY_MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(MCP_CONTRACT.read_text(encoding="utf-8"))
    known_tools = set(contract["tools"]) | {"wait_for_jobs"}

    referenced = {
        tool
        for case in manifest["cases"]
        for field in ("expected_tools", "forbidden_tools")
        for tool in case[field]
    }

    assert referenced <= known_tools


def test_tool_reliability_grader_requires_and_scores_three_runs(
    tmp_path: Path,
) -> None:
    manifest = json.loads(TOOL_RELIABILITY_MANIFEST.read_text(encoding="utf-8"))
    runs = []
    for case in manifest["cases"]:
        for run in (1, 2, 3):
            observation = {
                "case_id": case["id"],
                "run": run,
                "selected_tools": case["expected_tools"],
                "task_success": True,
                "schema_valid_after_one_retry": True,
                "unauthorized_calls": 0,
            }
            if case["category"] == "retrieval":
                observation["retrieval_hit_at_5"] = True
            if case["category"] == "citation":
                observation["source_admission_correct"] = True
            runs.append(observation)
    observations = tmp_path / "tool-runs.json"
    observations.write_text(json.dumps({"runs": runs}), encoding="utf-8")

    result = evaluate_tool_reliability(observations)

    assert result["passed"] is True
    assert result["run_count"] == 96
