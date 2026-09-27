#!/usr/bin/env python3
"""Offline reproducible inference, retrieval and passage-window comparison.

Run in a provisioned Scholens environment. Downloads, model conversion and
production configuration changes are deliberately separate operations.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
from tokenizers import Tokenizer

from scholens_ai import LocalOnnxTextEmbedder, build_document_passages
from scholens_ai.token_passages import iter_token_passages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "packages/scholens_ai/tests/fixtures/bilingual-retrieval.json"
        ),
    )
    parser.add_argument(
        "--strategy", choices=("legacy", "tokens", "both"), default="both"
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    corpus = json.loads(args.corpus.read_text())
    started = time.perf_counter()
    model = LocalOnnxTextEmbedder(args.model_dir)
    model.embed_query("inference warmup")
    cold_seconds = time.perf_counter() - started
    documents = [model.embed_passages([doc["text"]])[0] for doc in corpus["documents"]]
    matrix = np.asarray(documents)
    identifiers = [doc["id"] for doc in corpus["documents"]]
    recall, ndcg, durations, queries = [], [], [], []
    for query in corpus["queries"]:
        started = time.perf_counter()
        vector = model.embed_query(query["text"])
        durations.append(time.perf_counter() - started)
        queries.append(vector)
        ranked = np.argsort(-(matrix @ np.asarray(vector)))[:10]
        hits = [int(identifiers[index] in query["relevant"]) for index in ranked]
        recall.append(sum(hits) / len(query["relevant"]))
        ideal = sum(
            1 / math.log2(index + 2) for index in range(min(10, len(query["relevant"])))
        )
        ndcg.append(
            sum(hit / math.log2(index + 2) for index, hit in enumerate(hits)) / ideal
        )

    tokenizer = Tokenizer.from_file(str(args.model_dir / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    raw_content = "\n".join(doc["text"] for doc in corpus["documents"]) * 8
    strategies = {
        "legacy": (build_document_passages(raw_content), 8),
        "tokens": (tuple(iter_token_passages(raw_content, tokenizer)), 2),
    }
    benchmarks = {}
    for name, (chunks, batch_size) in strategies.items():
        if args.strategy not in {name, "both"}:
            continue
        trials, batches = [], []
        for _ in range(args.repeats):
            started = time.perf_counter()
            for offset in range(0, len(chunks), batch_size):
                tick = time.perf_counter()
                model.embed_passages(
                    [chunk.content for chunk in chunks[offset : offset + batch_size]]
                )
                batches.append(time.perf_counter() - tick)
            trials.append(time.perf_counter() - started)
        benchmarks[name] = {
            "chunks": len(chunks),
            "batch_size": batch_size,
            "trials_seconds": trials,
            "index_p95_seconds": float(np.quantile(trials, 0.95)),
            "batch_p95_seconds": float(np.quantile(batches, 0.95)),
        }
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mib = peak_rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    result = {
        "fixture_description": corpus["description"],
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "variant": args.variant,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "model_sha256": hashlib.sha256(
            (args.model_dir / "model.onnx").read_bytes()
        ).hexdigest(),
        "cold_seconds": cold_seconds,
        "query_p50_seconds": float(np.quantile(durations, 0.5)),
        "query_p95_seconds": float(np.quantile(durations, 0.95)),
        "recall10": float(np.mean(recall)),
        "ndcg10": float(np.mean(ndcg)),
        "peak_rss_mib": peak_mib,
        "index": benchmarks,
        "document_vectors": documents,
        "query_vectors": queries,
    }
    args.output.write_text(json.dumps(result))
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if not key.endswith("_vectors")
            }
        )
    )


if __name__ == "__main__":
    main()
