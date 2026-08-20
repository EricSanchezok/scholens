# 0029 — Local hybrid retrieval for stored papers

Status: Accepted
Date: 2026-08-20
Owners: Scholens

## Problem

Exact PostgreSQL full-text matching makes a growing Library difficult to use.
Joined words such as `codeworldmodel`, small title mistakes, and natural-language
recollections of a paper's subject or claim either miss known papers or require
the researcher to remember the source wording. Library and Project must share
one permission-safe retrieval behavior, and stored research text must not be
sent to an external embedding service merely to make it findable.

Semantic indexing is derived data and may be incomplete during rollout, worker
failure, or a model revision. Search therefore cannot depend on a fully
backfilled vector index for availability.

## Decision

Keep `PaperSearchPort` as the application boundary and make its default
PostgreSQL adapter hybrid. Authorization filters are applied inside every
candidate lane before ranking. The adapter combines compact exact matching,
`pg_trgm` similarity, weighted PostgreSQL full text, and cosine similarity over
a local `intfloat/multilingual-e5-small` ONNX projection, then fuses the ranked
lists with reciprocal-rank fusion.

The model repository commit and artifacts are pinned in Server and Jobs images.
Server embeds queries locally. Jobs may embed the bounded canonical
title/keywords/summary/abstract projection after PDF processing; Server owns
the versioned, source-digest-bound `DocumentSearchEmbedding` row. A repeatable
operator command backfills or refreshes existing documents in bounded batches.
If the model is absent, inference fails, or a document is not indexed, lexical
retrieval remains available and the public response reports its mode and index
coverage.

`pg_trgm` and `vector` are database-owner-installed extensions. The expand
migration adds derived columns, indexes, and the versioned projection table but
does not grant the product migrator or runtime role extension ownership.

## Alternatives considered

- Use embeddings alone. Rejected because exact identifiers, titles, authors,
  and newly ingested papers require deterministic lexical recall, and a vector
  backfill must not become an availability gate.
- Call a hosted embedding API. Rejected because it adds per-query latency,
  recurring cost, provider availability, and unnecessary disclosure of stored
  research and user queries.
- Add only fuzzy string matching. Rejected because it repairs spacing and
  spelling but cannot recover a paper from a paraphrased topic or claim.
- Put a separate search service in front of PostgreSQL. Rejected at the current
  collection scale because it adds another authorization projection,
  synchronization path, and production service without a demonstrated need.
- Use an LLM to classify or rewrite every query. Rejected because deterministic
  local retrieval is faster, cheaper, easier to evaluate, and does not require
  generative output in the request path.

## Consequences

Search remains a PostgreSQL-owned projection with no new network service, but
the database now requires pgvector and pg_trgm and runtime images carry a pinned
ONNX model. Model revision changes require an image update and bounded reindex.
Ranking has multiple explainable retrieval modes and needs a fixed evaluation
set covering exact, joined-word, typo, semantic, multilingual, authorization,
and degraded-index cases. Raw search text must not enter analytics logs.

The projection can be rebuilt from canonical Document data. It does not become
the source of paper metadata, Library membership, or Project authorization.

## Validation

CI proves migration convergence with the required extensions, callback
compatibility, local embedding shape and normalization, lexical fallback,
generated OpenAPI compatibility, frontend loading/empty/unavailable states,
and Library/Project browser behavior. Production rollout monitors semantic
coverage and repeats the bounded backfill until no candidates remain.
