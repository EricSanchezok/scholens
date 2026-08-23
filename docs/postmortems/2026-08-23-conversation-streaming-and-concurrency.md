# Conversation streaming and cross-conversation concurrency regression

- Date: 2026-08-23
- Status: Draft
- Severity: SEV-3
- Owners: Scholens

## Summary

Conversation final answers stopped displaying incrementally after structured
final-output validation was introduced. In the same Web session, an active
generation also prevented submission in another Conversation under the same
global, project, or paper surface. The first regression was introduced by
buffering the full structured output before the first final delta. The second
was an older client-lifecycle defect: one scope-level Boolean and stream ref
owned busy state even after the selected Conversation changed.

The corrective change restores provisional structured streaming with explicit
retraction and keys local submission ownership to the scope and Conversation.
It does not weaken final validation or change the Server rule that only one
response may run inside a single Conversation.

## Impact

Users waited until a tool boundary or the complete final answer before seeing
new assistant text. Users who navigated to another Conversation in the same
surface could not send there while the first local stream remained active.
The Server's per-user cross-Conversation capacity was still available, and
accepted background generations, persisted answers, authorization, citations,
and explicit cancellation were not lost or bypassed.

## Detection

A production mobile report identified both symptoms. Existing tests verified
event contents, terminal validation, detachable recovery, and same-Conversation
conflicts, but did not assert that one structured output produced multiple
public deltas or that navigation to a second Conversation released only the
local subscriber. No release gate measured first-visible-delta behavior.

## Timeline

- 2026-08-20: detachable generation made accepted Server work independent of a
  browser subscription, while the Web hook retained scope-level local busy
  ownership.
- 2026-08-22: structured `final_answer` validation removed unsafe terminal text
  but buffered every final answer until full validation.
- 2026-08-23: production mobile use exposed delayed final text and the blocked
  second-Conversation submission.
- 2026-08-23: root causes were reproduced from code and history; protocol,
  lifecycle, compatibility, and regression-test changes were prepared.

## Contributing factors

- Output validity and publication timing were represented as one boundary
  instead of separate provisional and committed states.
- The Web session hook scoped local ownership to its mounted surface, not to
  the selected Conversation identity.
- Async cleanup checked one stream object but had no independent submission
  token, so the design could not prove that an old callback lacked authority
  over a newer Conversation.
- Contract tests covered event ordering but not incremental structured chunks,
  retraction, or rolling compatibility with strict old clients.

## Resolution and recovery

The Server now partially validates and streams the structured answer as a
provisional item, retracts it when full validation retries, and buffers those
semantics for v1 clients. The Web reducer handles retraction, and the session
hook detaches on Conversation identity changes while leaving accepted Server
work running. Submission tokens prevent stale callbacks from releasing a newer
Conversation's state. Production recovery remains pending deployment and
post-deploy mobile verification, so this record remains Draft.

## Corrective actions

| Action                                                                                      | Owner    | Status | Tracking link     |
| ------------------------------------------------------------------------------------------- | -------- | ------ | ----------------- |
| Stream partial structured answers with validated completion and typed discard               | Scholens | Done   | This pull request |
| Add v1/v2 SSE negotiation and rolling compatibility buffering                               | Scholens | Done   | This pull request |
| Bind Web submission ownership to scope + Conversation with stale-callback tokens            | Web      | Done   | This pull request |
| Gate incremental deltas, discard, cross-Conversation navigation, and generated contracts    | Scholens | Done   | This pull request |
| Verify first-token display and parallel Conversations on production mobile after deployment | Scholens | Open   | This pull request |

## Lessons

Validation and streaming are compatible only when provisional state is explicit
from provider output through transport and UI. Detachable Server work also
requires detachable client ownership: route lifecycle may release a subscriber,
but only an explicit Stop may cancel accepted generation. Timing and ownership
properties need behavioral tests, not only final-state assertions.
