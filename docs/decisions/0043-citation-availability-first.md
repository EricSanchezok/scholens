# 0043 — Citation availability is separate from answer availability

Status: Accepted
Date: 2026-08-31
Owners: Scholens Conversation Platform

## Problem

The Conversation Agent currently treats malformed citation markers, missing
references, and visible placeholder labels as fatal output validation errors.
After the bounded `ModelRetry` budget is exhausted, a safe non-empty answer is
discarded and the response is exposed as `llm_provider_response_invalid`. This
made citation formatting a single point of failure for an otherwise usable
answer in production.

Provider APIs increasingly return answer text and attribution metadata as
separate structures. OpenAI annotations, Gemini grounding supports/chunks,
Anthropic citation blocks, and Bedrock `citations[]` all allow the application
to discard an attribution without discarding the text. Research systems also
use post-hoc claim verification and revision rather than requiring one perfect
inline protocol emission.

## Decision

Scholens uses an availability-first, provenance-strict contract:

1. Answer lifecycle remains `running | completed | failed | cancelled`.
2. Citation lifecycle is additive metadata in `ConversationCitationSummary`:
   `not_required | complete | partial | unavailable | pending`.
3. Grounding confidence is separate: `not_evaluated | verified | mixed |
   unverified`.
4. Citation protocol errors receive bounded model repair attempts. Once the
   repair budget is exhausted, the server publishes sanitized visible prose,
   drops invalid annotations, completes the response, and records the status.
5. Hard failures remain fatal: empty visible output, private protocol leakage
   that cannot be removed, provider transport/auth/content rejection, stream
   corruption, orchestration limits, and persistence failures.
6. `ReferenceBundle.sources` contains only sources attached to valid answer
   spans. Retrieved-but-unlinked sources are counted in the summary and are
   never presented as proof.
7. A provider adapter boundary normalizes native metadata and optional
   structured `{quote, source_keys}` attributions into server-owned source keys.
   Unknown provider identifiers are dropped. The legacy nonce marker parser
   remains as a compatibility adapter until telemetry shows zero use.
8. When native metadata is unavailable, bounded deterministic post-hoc claim
   alignment may add a citation only for a normalized containment match. Source
   similarity is candidate ranking, never evidence. The synchronous verifier
   is capped at 24 claims, three candidates per claim, and two seconds.
9. The existing HTTP/SSE and persistence shapes are extended additively. A
   `references` event may carry an empty bundle and a citation summary when
   sources were retrieved but no valid attribution survived. A future
   `citation_update` event may enrich a completed response without changing its
   text.
10. The source panel is the only user-visible degradation surface. The answer
    remains copyable and does not receive a global error banner for citation
    soft failures.

## Alternatives considered

- **Fail closed after every citation error.** Rejected because it couples
  answer availability to a presentation-level protocol and caused the
  production incident.
- **Ignore all citations and show every retrieved source.** Rejected because
  it falsely implies that similar or merely retrieved sources support every
  claim and weakens provenance guarantees.
- **Require provider-native structured output immediately.** Rejected because
  providers differ in metadata shape and some citation features are not
  compatible with strict JSON output. The adapter and legacy paths allow
  incremental migration.
- **Run an unbounded second model for every answer.** Rejected because it
  creates unpredictable latency and cost. Claim-level recovery is bounded and
  conservative; difficult claims remain unverified.

## Consequences

Safe answers remain available during citation-format regressions, while source
quality becomes observable instead of hidden behind a generic provider error.
The response trace and generated client contract gain additive fields, the
frontend source panel must render explicit partial/unavailable states, and
metrics must report citation coverage and precision independently. Provider
adapters and offline corruption fixtures become maintained compatibility code.

## Validation

The server test suite proves that malformed, stale, unknown, and visible
citation labels never hide non-empty safe prose; source bundles contain only
server-admitted keys; provider fixtures normalize or drop metadata safely; and
SSE/persistence complete the response. Web tests cover source-panel states,
refresh, replay, dark mode, and narrow layouts. Production acceptance tracks
answer completion, soft/hard citation failures, coverage, precision, verifier
timeouts, and latency separately for each model profile. The committed offline
manifest is executable with `python -m evals.run_citation_resilience_eval`; it
is deliberately redacted and checks structural precision independently from
coverage.
