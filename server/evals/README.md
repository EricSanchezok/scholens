# Scholens evaluations

This directory contains maintained end-to-end and offline evaluations.

## Tool reliability

`tool_reliability_eval_manifest.json` contains 32 redacted acceptance scenarios
covering non-overlapping tool routing, exact versus conceptual retrieval,
single-step recovery, and citation admission. Run every scenario three times in
the live-model staging harness, export the redacted observations, and grade them
against the committed thresholds before a tool-catalog or retrieval release:

```bash
cd server
uv run python -m evals.run_tool_reliability_eval /path/to/redacted-runs.json
```

The input contains exactly three records per case with `case_id`, `run`,
`selected_tools`, `task_success`, `schema_valid_after_one_retry`,
`unauthorized_calls`, and category-specific `retrieval_hit_at_5` or
`source_admission_correct`. It must contain no prompts, arguments, paper text,
provider bodies, credentials, or resource IDs. CI validates the manifest shape, catalog
references, deterministic retrieval behavior, and source-admission regressions;
it never requires provider credentials or production text.

## Citation resilience

`citation_resilience_eval_manifest.json` is a redacted, deterministic
acceptance set for production-shaped stale markers, malformed protocols,
unknown source keys, multi-document attributions, and conservative post-hoc
recovery. It deliberately contains no raw production prompt, provider body,
nonce, or private source identifier.

Run it without a live model or external service:

```bash
cd server
uv run python -m evals.run_citation_resilience_eval
```

The command reports structural precision and citation coverage separately.
Semantic precision for uncertain claims is measured by the optional bounded
verifier/evaluation pipeline, never inferred from source similarity alone.

## Data Table extraction

`run_data_table_eval.py` seeds the bundled PDFs into a local Scholens stack,
submits real Data Table jobs, and grades primitive and derived values.

Prerequisites:

- Server, Jobs worker, broker, PostgreSQL, and S3 are running.
- `EVAL_USER_ID` is the numeric ID of an existing sanchezcloud-identity user.
- `EVAL_BEARER_TOKEN` is a valid sanchezcloud-identity bearer token for that same user.
- The user has enough Token Credits for the requested runs.

```bash
cd server
uv run python -m evals.run_data_table_eval --runs 1
```

Use `--seed-only`, `--skip-seed`, or `--grade-only` for narrower workflows.
Results are written to `evals/results/eval_data_table.json`.

The committed manifest defines the extraction columns and expected values.
Fixture titles, authors, download sources, licenses, and checksums are recorded
in [`seed_data/README.md`](seed_data/README.md).
