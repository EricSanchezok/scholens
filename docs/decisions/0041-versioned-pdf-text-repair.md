# 0041 — Versioned PDF text repair without destructive re-ingestion

Status: Accepted
Date: 2026-08-24
Owners: Scholens

## Problem

Some otherwise readable PDF documents contain the Unicode replacement character
(`U+FFFD`) because the primary parser decoded a damaged text layer. Re-running the
ordinary ingestion task is unsafe: it can overwrite canonical content before the
candidate is proven better, duplicate user-visible jobs, race annotation writes,
or bind a callback to a newer document generation. A production backfill also
needs bounded work, retry limits, resumability, and isolation from requester Job
feeds.

## Decision

Use a dedicated, versioned `repair_pdf_text` worker task. The task receives only
the shared eleven-field repair contract and writes versioned candidate artifacts;
it never changes the canonical document pointer. A Server callback validates the
repair revision, attempt, source Job, source-content digest, document identity,
result Job identity, and artifact-key namespace before considering the candidate.

The candidate replaces canonical text only when replacement-character count
improves and conservative, order-preserving semantic evidence says the text did
not diverge. Presence-only sampling is insufficient because a parser can retain
every sampled phrase while reversing columns or paragraphs. The
same transaction locks the durable repair Job and Document, rechecks the source
generation, reanchors every uniquely mappable parsed-text annotation, replaces
the passage index, invalidates derived reflow, and switches the canonical pointer.
An ambiguous annotation or unsafe text comparison rejects the candidate without
partially updating any of those projections. Historical annotation quote and
position sizes are measured through a locked scalar query before the bounded
rows are hydrated, so pre-validation legacy JSONB cannot bypass the callback's
memory ceiling. Obsolete callbacks become terminal
failed maintenance Jobs so they are not redelivered and do not close a newer
source-content digest.

Historical selection is an explicit operator command, not an application-startup
side effect. It keyset-scans small pages, locks candidates with `SKIP LOCKED`,
rechecks them inside per-row savepoints, and binds idempotency to repair revision,
document, canonical source Job, source-content digest, and attempt. One active or
successful repair closes only that source generation. Failed or cancelled work
may retry at most three times. Selection is capped at 50 documents, 32 MiB per
document, and 64 MiB per invocation. Repair Jobs carry the domain marker
`job_visibility=maintenance` and are excluded from requester list, get, wait,
retry, and cancel paths. They are document-global maintenance records and carry
no Project foreign key, even when the historical source Job was project-scoped.
This avoids acquiring a Project key-share lock after Document selection and
keeps the transaction compatible with Project deletion's Project-before-Document
lock order.

Jobs and Server share a separate signed-callback byte contract: 64 MiB for the
exact compact JSON body, 40 MiB UTF-8 for candidate canonical text (the 125%
quality ceiling over a 32 MiB source), and 2 MiB for encoded page offsets. Jobs
checks the encoded body before opening HTTP; Server checks `Content-Length` and
then enforces the same aggregate limit while streaming a chunked request.
Callback routes expose no eager FastAPI body parameter and parse only the
bounded, signature-verified byte cache, so framework validation cannot consume
the request ahead of the transport guard.

The fallback parser is also used prospectively when primary output contains
`U+FFFD`. It is accepted only when it reduces replacements, remains within the
configured length ratio, and matches enough distributed semantic evidence.
Otherwise ingestion completes with the readable primary text downgraded to
`text_only` plus a stable warning code.

## Alternatives considered

- Rewrite contaminated rows directly in an operator script. Rejected because it
  bypasses worker isolation, callback validation, annotation reanchoring, search
  rebuilding, audit Jobs, and transactional rollback.
- Re-run the ordinary `pdf_process` task. Rejected because its lifecycle owns
  initial ingestion, memberships, quota reservations, and user-visible state; a
  historical repair has different authorization and replacement semantics.
- Accept any fallback with fewer replacement characters. Rejected because a
  shorter but unrelated extraction can appear numerically better while corrupting
  citations, annotations, and search results.
- Install a database extension to hash every candidate in the scan query.
  Rejected because the bounded selector can hash one locked row at a time without
  adding a production schema dependency.

## Consequences

Repair has a deliberately larger implementation surface: a shared queue contract,
candidate selector, maintenance visibility policy, callback validator, canonical
replacement transaction, and operator runbook must evolve together. Versioned
artifacts have an explicit lifecycle owner: rejected, failed, obsolete, and
not-applied callbacks enqueue deletion of the exact artifact keys derived from
the persisted repair-job namespace; an applied callback deletes superseded
canonical parser artifacts; final Document GC enumerates every repair Job still
bound to that Document and includes its strictly derived namespace in the same
transactional storage-deletion outbox. Callback result JSONB retains only a
bounded audit summary (digests, counts, parser identity, artifact keys, and
outcome), never candidate text or page maps. Document GC also sanitizes any
legacy repair result before the Document foreign key is cleared. Operators must
first deploy worker support, then Server support, perform a dry run, and only
then opt into bounded apply batches.

The design preserves the last readable canonical text under worker failures,
stale callbacks, unsafe candidates, and partial-batch errors. It also gives an
operator exact counts, work bytes, new repair Job IDs, and sampled document IDs
without exposing maintenance Jobs to ordinary users.

## Validation

- Shared-package tests lock the task name and exact keyword contract.
- Jobs tests cover fallback acceptance/rejection, versioned artifact paths, and
  the dedicated task route.
- Server tests cover candidate bounds, source/digest/attempt idempotency,
  maintenance visibility, stale callback termination, safe replacement,
  ambiguous reanchors, passage rebuilding, reflow invalidation, bounded durable
  results, exact terminal artifact cleanup, and final Document-GC cleanup.
- Shared-package tests include reversed-paragraph and reversed-column adversarial
  candidates so evidence must remain in source order.
- The deployment runbook requires dry-run counts and worker registration before
  any production `--apply`; this change does not itself execute production repair.
- `./scripts/run-gates.sh shared-packages`, `jobs`, `server`, and `docs` own the
  deterministic regression checks.
