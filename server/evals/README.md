# Scholens evaluations

This directory contains the maintained end-to-end Data Table evaluation.

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
