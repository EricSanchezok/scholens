# ADR 0060: Personal verbatim evidence receipts

Status: Accepted

## Problem

Metadata extraction allowed paraphrased highlights, while persisted anchors
required exact source text. Most rejected highlights could never satisfy that
contract. A document-wide assistant-annotation check also suppressed every
subsequent highlight after a partially successful result.

## Decision

Metadata prompts contain bounded overlapping source segments with stable IDs
bound to the complete canonical content digest and character bounds. Highlights
and summary citations ask for verbatim quotes and the supplied segment ID.
Explanation belongs in the annotation or summary, never in the quote.

`scholens_ai.evidence` owns deterministic segmentation and reversible Unicode
compatibility decomposition plus whitespace normalization. Case, punctuation
and wording are preserved. A unique match is required inside the declared
segment. A stale segment, ambiguous quote, paraphrase or partial expanded
character cannot produce an anchor. Persisted quote text is sliced from the
unchanged source, with exact canonical offsets. Legacy unsegmented results
require a unique match across the source; normalization uses bounded blocks.

The Research persistence adapter owns one personal evidence receipt per user,
document, canonical content digest and evidence digest. Receipt, annotation and
initial comment share a transaction. The document lock serializes content
repair and annotation creation. A retry inserts missing evidence without
changing an existing annotation or comment. Deleting an annotation leaves a
receipt with a null reference, so delayed delivery does not resurrect it.
Document and account deletion cascade their receipts.

The additive `ai_annotation_evidence` table is migrated before adoption. Older
callbacks omit segment IDs and remain valid. The dedicated persistence adapter
adopts only matching existing personal assistant anchors; it never treats a
human note, Project annotation or another user's evidence as a duplicate.
Source job and execution generation are recorded when available. The adapter
owns this legacy adoption path until existing anchors have receipts, accepted
legacy jobs have drained, and the 90-day compatibility plus 30-day rollback
window has passed. Removal requires a reviewed contract stage.

Coverage telemetry distinguishes total candidates, anchored, already present,
created and rejected candidates; rejection reasons are bounded codes. No quote
or source text is logged. These counts describe processing coverage, not the
scientific truth of the model's interpretation.

## Alternatives considered

Fuzzy substring matching was rejected because a plausible short match can
silently attach a claim to the wrong source location. Retrying the full document
with a boolean deduplication flag cannot repair partial results. Deleting and
recreating AI threads on every retry would destroy user discussion and edits.

## Consequences

Receipt storage grows with accepted personal evidence and is removed with its
document or account. The migration must precede consumers. Conservative rejection
can reduce coverage for ambiguous or altered quotes; it cannot be replaced by
fuzzy matching to improve a success counter. Partial coverage stays observable
and retryable without modifying existing user work.

## Validation

Direct bilingual and Unicode fixtures exercise original offsets, repeated
quotes, stale segments, bounded segmentation and normalization boundaries.
Real PostgreSQL tests cover concurrent delivery, partial retry, user isolation,
transaction rollback, legacy adoption, removed access and deletion tombstones.
No paid provider regeneration is required to validate or adopt receipts.
