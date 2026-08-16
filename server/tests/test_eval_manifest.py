import ast
import hashlib
import json
import math
import operator
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = SERVER_ROOT / "evals"
SEED_ROOT = EVAL_ROOT / "seed_data"
MANIFEST_PATH = EVAL_ROOT / "data_table_eval_manifest.json"
ATTRIBUTION_PATH = SEED_ROOT / "README.md"


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
