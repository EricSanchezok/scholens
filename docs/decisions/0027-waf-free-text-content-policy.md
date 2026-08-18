# 0027 — WAF free-text content policy

Status: Accepted
Date: 2026-08-18
Owners: Scholens

## Problem

Production `AWSManagedRulesCommonRuleSet` blocked legitimate academic text with
403 at the edge. Selecting a passage containing path-like tokens (for example
`../cwm-sft` from a model-name list) and submitting it to
`POST /api/v1/papers/{document_id}/selection-translations` tripped
`GenericLFI_BODY`, which treats `../` sequences as local-file-inclusion
attacks. The request never reached FastAPI, the API log group showed no
request, and the frontend degraded to a generic "translation was not
completed" message with no actionable reason.

The same false-positive class applies to every public route whose JSON body
carries free-form user or document text: annotation quotes and comments,
library metadata overrides, project descriptions, onboarding free-text
fields, search queries, and conversation content. The existing
`LargeBodyPathSet` exemption was size-motivated and excluded only
`SizeRestrictions_BODY`; the remaining body content rules (including LFI)
still ran against those paths, so the incident class also existed latently on
`/mcp`, `conversations`, and `paper-ingestions`. Nothing in CI prevented a new
public endpoint from silently landing outside the reviewed WAF body policy.

## Decision

The common-threat rule set is split by path into two explicit scopes, both
under the existing two CRS references (WCU unchanged):

- Structured paths (auth, billing, access keys, invitations, tags, library
  membership, integration credentials, and every other body-bearing route not
  listed below) keep the full CRS body inspection.
- Free-text content paths — `LargeBodyPathSet` (`^/mcp$`, `conversations`,
  `paper-ingestions`) plus the new `ContentFreeTextPathSet` (selection
  translation, annotation threads/comments, library paper metadata,
  translation preferences, projects, onboarding, audio-overview instructions,
  search) — get `RuleActionOverrides` turning the five CRS body rules
  (`SizeRestrictions_BODY`, `EC2MetaDataSSRF_BODY`, `GenericLFI_BODY`,
  `GenericRFI_BODY`, `CrossSiteScripting_BODY`) and the two query-string rules
  (`GenericLFI_QUERYARGUMENTS`, `CrossSiteScripting_QUERYARGUMENTS`) into
  Count mode, so legitimate content is logged and metered instead of blocked.

Academic text legitimately contains path-like, URL-like, code-like, and
metadata-address-like tokens, so CRS body content signatures are a
false-positive source on those routes, not protection. The application layer
remains the real boundary there: pydantic length caps, JSON parsing, auth,
per-module authorization, and worker-side SSRF guards (`ipaddress.is_global`)
on the ingestion URL path. The origin-token rule, IP reputation list, client
rate limit, and all header/URI rules are unchanged. No explicit Allow rule is
used, because an Allow match terminates WAF evaluation and would skip IP
reputation.

Every body-bearing public write route must be explicitly classified by
`test_waf_free_text_path_sets_classify_every_public_write_route` in
`server/tests/test_deployment_contract.py`: the route either matches one of
the two path sets or appears in the structured whitelist. A new or renamed
route in neither bucket fails the deployment gate — the WAF classification is
part of the change that introduces the route.

WAF traffic logs stream to the `aws-waf-logs-scholens-production` CloudWatch
Logs log group (30-day retention, template-owned) with `x-scholens-origin`,
`cookie`, and `authorization` redacted. Request sampling stays disabled on the
Web ACL and every rule because requests carry the origin secret; logging and
sampling are separate controls. The reader treats a codeless 403 from a
translation request as `edge_blocked` and shows an actionable explanation
instead of a duplicated generic title.

## Alternatives considered

- Only add routes to `LargeBodyPathSet` without touching the reviewed rule.
  Rejected: that rule only excluded `SizeRestrictions_BODY`, so LFI and the
  other body content rules would keep blocking the incident class.
- A third CRS reference with per-path exclusions. Rejected: every CRS
  reference costs 700 WCUs and the two scopes share one override set, so a
  third reference would exceed the 1,500-WCU base price without benefit.
- An explicit Allow rule for free-text paths. Rejected: Allow terminates
  evaluation and would skip the IP reputation list and rate limiting.
- A label-matching pipeline (count rules, then a post rule matching
  `awswaf:managed:*` labels for allowed paths). More flexible, but adds
  template complexity and testing cost; retained as the evolution path if
  per-field differentiation is ever needed.
- Exempting integration credentials and the Zotero `return_path` route.
  Rejected: credentials are sensitive and rarely path-like; the application
  allows `/foo/../bar` shapes in `return_path`, so WAF LFI inspection there is
  real defense in depth.
- Frontend-only handling (retrying or presenting the 403). Rejected: the
  block happens before the API and would mask the systemic false-positive
  class.

## Consequences

New body-bearing public write routes now carry a visible WAF classification
obligation, enforced by the deployment gate. `ContentFreeTextPathSet` holds
exactly ten patterns, the per-set service limit; a future free-text route
must either merge into an existing pattern or add a third regex set joined
into the same Or statements (no additional WCU). The broad
`^/api/v1/projects(?:/.*)?$` pattern counts down some nested structured
endpoints (invitations, members, transfer) whose enum/UUID bodies cannot trip
the relaxed rules; the drift test's whitelist cross-check keeps that
over-approximation visible and prevents double classification. WAF log
ingestion and 30-day retention add CloudWatch Logs cost; the redaction list is
part of the deployment contract test and must stay complete if more sensitive
headers appear.

## Validation

- `./scripts/run-gates.sh deployment` — cfn-lint plus deployment contract
  tests asserting both path sets, the Or/Not scope-downs, the exact seven
  RuleActionOverrides, the three redacted fields, and the full
  OpenAPI-driven classification drift test.
- `./scripts/run-gates.sh server` and `./scripts/run-gates.sh web` — snapshot
  unchanged, translation unit tests including the codeless-403 mapping, and
  i18n catalog alignment.
- Post-deploy: the incident paper's `../cwm-sft` selection translates with
  200; the reviewed-large-body metric reports CountedRequests for
  `GenericLFI_Body`; the WAF log group shows the COUNT record with redacted
  origin header.
