# 0017 — Evidence-driven Reader reflow and controlled document translation

Status: Accepted
Date: 2026-08-14
Owners: Scholens
Supersedes: [ADR 0016](./0016-lossless-reader-reflow-and-lazy-translation.md)

## Problem

Classifying parser Markdown without consulting the PDF preserved source tokens,
but it did not produce a trustworthy reading document. Parser artifacts such as
literal `<sup>` tags, replacement characters, incorrect line breaks, flattened
tables, lost equations, and missing figures reached the UI. Treating all model
rewriting as forbidden also meant the system could not repair defects that were
unambiguous in the original page. The result was technically lossless but often
less readable than the PDF and, in malformed regions, actively confusing.

Full-document translation was also presented as a second row inside reflow. It
consumed scarce mobile space, hid important controls behind a binary switch, and
made display mode, references, language, and custom instructions impossible to
understand or configure.

## Decision

Reflow is a derived, evidence-bound academic reconstruction. A reflow job reads
both the canonical Markdown and the original PDF. Every original source unit is
persisted unchanged in `source_markdown`; the separately persisted
`render_markdown` may contain deterministic repairs or a visually verified
repair. Blocks retain their source page and normalized PDF rectangle whenever
the text layer can locate it.

Deterministic repair removes comments and unknown tags while preserving visible
text, converts supported superscript and subscript markup to safe math, and
joins parser-only line-wrap hyphenation. Formula, table, replacement-character,
and structure conflicts may use the independent provider-neutral
`reflow_repair` multimodal profile with a bounded page crop. Model output is
accepted only when source coverage, ordering, length, markup safety, visual
evidence, and a local confidence threshold agree. Failure or low confidence
degrades only that block to a PDF fallback; a model guess is never displayed.
Document text is untrusted evidence and cannot alter the repair instructions.

Reflow recognizes explicit academic block kinds including paper metadata,
abstract, keywords, equations, tables, figures, captions, footnotes, and
references. Raster images are extracted directly. Vector or composite figures
are clipped from their visible page region. Derived assets have deterministic
private object keys, checksums, dimensions, page numbers, and normalized source
rectangles. Clients receive metadata and an authorized short-lived URL, never
the object key. Retrying replaces blocks and assets atomically, then schedules
only obsolete objects for deletion. Physical Document collection owns final
asset cleanup; removing one Library reference does not delete shared Document
assets.

Reader renders a safe academic Markdown subset. Arbitrary raw HTML is never
enabled. GFM tables, line breaks, superscript, subscript, and LaTeX math are
handled by explicit renderers. The PDF remains the final authority and every
repair or degraded block can navigate back to its source region.

Full translation is a Reader toolbar capability available in reflow and visibly
disabled in PDF view. `translate=full` remains shareable URL state, while target
language and display preferences are user-owned. The default display is
bilingual source followed by translation; translation-only is optional.
References require an explicit opt-in. Authors, affiliations, code, equations,
and image pixels are never translated. Translation cache identity uses the
repaired display content hash. Work remains near-viewport lazy and bounded to
two concurrent streams.

Desktop exposes settings in a popover; narrow screens use a bottom sheet. The
toolbar stays one row and its panel toggle remains pinned to the same right-edge
position in both panel states. Tables and code may scroll within their own
blocks; the Reader surface itself may not scroll horizontally.

## Alternatives considered

- Continue layout-only classification. Rejected because it cannot repair
  visible parser defects or restore figures and tables.
- Trust a whole-document model rewrite. Rejected because it cannot prove source
  coverage, makes hallucination hard to localize, and weakens PDF traceability.
- Accept model self-reported confidence. Rejected because confidence without
  source coverage and PDF evidence is not a correctness signal.
- Make visual AI mandatory for every block. Rejected because prose has a strong
  deterministic path and one provider outage must not fail the whole paper.
- Render arbitrary HTML emitted by parser or model. Rejected because it expands
  the injection surface and makes content policy impossible to audit.
- Overlay translated text on PDF geometry. Rejected for this phase because
  preserving layout, selection, accessibility, and figure text requires a
  separate coordinate-aware product contract.

## Consequences

Jobs now owns bounded PDF evidence extraction and repair validation in addition
to layout classification. Server owns block/asset persistence, authorized asset
URLs, retry replacement, and storage lifecycle. Web owns safe academic
presentation, toolbar settings, lazy translation, and exact source navigation.

The original Markdown remains available for audit, but the translation source
and Reader presentation use `render_markdown`. Reflow has more rows and derived
objects, so schema reset is required during pre-release development. Model
configuration gains `SCHOLENS_AI_REFLOW_REPAIR_*`; a missing credential is a
supported degraded state, not a document failure.

## Validation

Jobs tests cover deterministic markup repair, prompt-injection isolation,
source coverage, page rectangles, image extraction, visual acceptance, and
per-block degradation. Server tests cover callback integrity, authorized asset
URLs, atomic replacement, and physical cleanup. Web gates cover every semantic
block, safe math/table rendering, translation modes, desktop popover, mobile
sheet, exact PDF navigation, and 320/390px horizontal-overflow regression.
