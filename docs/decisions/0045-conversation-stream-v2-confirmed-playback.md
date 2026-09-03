# ADR 0045: Conversation stream v2 and confirmed playback

## Status

Accepted

## Problem

Conversation SSE already survives subscriber detachment, but long tool phases can
look idle and Redis persistence can delay the live path. The Web also reparses
the entire Markdown answer for every delta. These failures are perceived as a
non-streaming answer even when the provider is producing data.

## Decision

Conversation generation receives a new `/api/v2` streaming boundary. Direct and
detachable requests use one replayable event sequence with a response-local
`seq`, stable part IDs, and part versions. The public event set follows
research-agent's lifecycle semantics: explicit phases, safe activity snapshots,
provisional candidates, a selected `response.ready`, and one terminal event.
Provider text deltas are forwarded to the provisional candidate as they arrive;
if the same model step later reveals a tool call, the speculative candidate is
reset and published as bounded progress instead.
Raw tool arguments, provider heartbeats, internal iteration, and chain-of-thought
remain private.

The worker emits live events independently of Redis persistence through a
bounded asynchronous sink. Redis remains a bounded replay log and PostgreSQL
remains canonical. SSE comments are transport keepalives only.

The Web folds the event log into canonical state and renders it through a
confirmed target-to-published projection. Playback uses one animation-frame
scheduler in the foreground, a bounded hidden-document timer, adjacent-delta
coalescing, and terminal-event flushes. Settled Markdown blocks are memoized so
only the active block reparses. Every real activity remains a separate Worklog
row.

The replacement Web switches once to v2. `/api/v1` remains a thin adapter during
the rolling deployment and is removed only after its documented deprecation
window and zero-traffic evidence.

## Alternatives considered

- Tuning Cloudflare or adding more transport comments alone was rejected because
  current long gaps are also produced upstream during model/tool phases.
- Keeping `/api/v1` and adding a second candidate stream was rejected because it
  preserves two event authorities and the same reconnect ambiguity.
- A browser-only typewriter was rejected because it would hide transport stalls,
  fabricate cadence, and diverge from canonical response state.

## Consequences

- Long-running tool work has an honest visible phase without fabricated facts.
- Reconnects can replay or deduplicate by cursor, sequence, and version.
- Redis latency no longer directly controls model-to-client cadence.
- The v2 contract is intentionally incompatible with the legacy event union;
  generated OpenAPI artifacts and Web types must be updated together.
- More event metadata and reducer invariants require deterministic state-machine
  tests and content-free production timing telemetry. The v1 and v2 OpenAPI
  snapshots are generated independently so the Web decoder cannot drift from
  the v2 envelope.
