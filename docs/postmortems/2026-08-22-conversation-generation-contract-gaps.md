# Conversation generation contract gaps produced incomplete product output

- Date: 2026-08-22
- Status: Draft
- Severity: SEV-3
- Owners: Scholens

## Summary

The detachable Conversation generation release exposed three gaps in the
production path: resumed workers did not start the initial-title sidecar,
sanitized tool validation details were discarded before the model could repair
its call, and plain model text could be accepted as a completed answer. The
last gap allowed internal planning and private citation instructions to appear
as user-visible content.

The code correction restores worker-owned titles, makes argument validation
repairable, and requires a validated structured final answer. Production
recovery remains open until the change is deployed and default titles are
backfilled.

## Impact

- New conversations generated through the asynchronous production path could
  remain titled `New conversation` even after a successful first response.
- One reported research conversation repeatedly failed local knowledge searches
  while external connector searches succeeded; the UI obscured that mixed
  result and labeled the absence of final citations as zero sources.
- One confirmed response persisted internal planning and citation-protocol text
  as a completed answer. No credential, raw tool argument, or raw tool result
  exposure was identified.

## Detection

The user reported all three symptoms with production screenshots. Existing
worker logs recorded task receipt but not the safe validation error code, and
the response was marked completed, so no failure alarm fired. Repository and
production-state inspection connected the title regression to worker resume,
the repeated tool calls to discarded validation details, and the incomplete
answer to the plain-string completion boundary.

## Timeline

- 2026-08-20 — detachable Conversation generation becomes the production path.
- 2026-08-22 21:01–21:02 CST — screenshots capture default titles, mixed tool
  failures, and a completed internal draft.
- 2026-08-22 — investigation reproduces the lifecycle conditions and identifies
  all three contract gaps.
- 2026-08-22 — corrective implementation and regression coverage are prepared;
  deployment and title backfill remain pending.

## Contributing factors

- Title generation was gated by the inline request's `turn_created` flag even
  though the durable worker resumes an already-created turn.
- The dispatcher produced safe field-level validation details, but the Agent
  adapter replaced them with a generic message and recorded no error-code
  dimension.
- `str` was an allowed terminal output and the adapter validated only that the
  resulting text was non-empty.
- Text streamed before the complete model node established whether it was
  progress, a final answer, or an invalid terminal attempt.
- UI summaries combined mixed tool outcomes and called final citation count
  simply “sources.”

## Resolution and recovery

The change introduces a structured final-answer tool, buffers model text until
classification, retries safe argument-validation failures, restores title
generation for resumed workers, and makes mixed operation state plus cited
source count explicit in the Web UI. After deployment, operators will dry-run
and apply the existing idempotent default-title backfill command.

## Corrective actions

| Action | Owner | Status | Tracking link |
| --- | --- | --- | --- |
| Restore worker title sidecar and cover resumed generation | Scholens | Complete | Current PR |
| Require validated structured final output | Scholens | Complete | ADR 0036 |
| Return safe tool validation retries and error-code metrics | Scholens | Complete | Current PR |
| Clarify mixed operations and cited-source copy | Scholens | Complete | Current PR |
| Deploy and run default-title backfill | Scholens | Open | Release follow-up |

## Lessons

Durable execution changes must retest every sidecar against resumed state, not
only the main response transaction. “Non-empty text” is not a sufficient final
answer contract. Sanitized validation information is part of Agent reliability
even when raw arguments correctly remain private.
