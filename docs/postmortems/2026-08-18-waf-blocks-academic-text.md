# Production WAF blocked academic text with GenericLFI_BODY

- Date: 2026-08-18
- Status: Final
- Severity: SEV-3
- Owners: Scholens

## Summary

Selection translation on `scholens.sanchezcloud.net` intermittently failed
with a generic "translation was not completed" message. The AWS WAF in front
of the ALB blocked `POST /api/v1/papers/{document_id}/selection-translations`
with 403 before it reached FastAPI because
`AWSManagedRulesCommonRuleSet`'s `GenericLFI_BODY` matched path-like tokens
(`../cwm-sft`) inside a legitimate paper excerpt. The failure depended on the
selected text, so some translations succeeded while others were silently
blocked.

## Impact

- Reader selection translation failed for passages whose text resembles file
  paths or code (the affected paper is a concrete repro).
- No data loss, no outage of other product surfaces. Auth, ingestion,
  conversations, and MCP traffic were unaffected.
- The latent false-positive class also applied to the previously exempted
  `/mcp`, `conversations`, and `paper-ingestions` paths, which excluded only
  the body-size rule while the body content rules (including LFI) still ran.

## Detection

The user reported the failure with a screenshot. Initial analysis ruled out
provider, quota, and SSE failures from API logs (the only matching request was
200 with a normal body), then the browser console showed the decisive signal:
the POST returned 403 while sibling requests succeeded. WAF CloudWatch
metrics showed `BlockedRequests` on the standard-bodies rule at the incident
times; the API log group had no corresponding request because the block
happened at the edge. The existing signals did not help earlier because WAF
logging was disabled and sampled requests are intentionally off (requests
carry the origin secret).

## Timeline

All times CST on 2026-08-18 unless noted.

- 09:41, 10:02 — user attempts selection translation; browser console shows
  403 for the selection-translations POST.
- 09:45 — investigation begins: CloudWatch API logs show no failing request
  and no `translation.stream.failed` events.
- 10:10 — the successful same-route request at 01:41 UTC (200, 4.9 s) proves
  the failure depends on the selected text, not the provider.
- 10:15 — WAF metrics show `BlockedRequests` under the standard-bodies rule
  aligned with the incident times; the label analysis identifies
  `GenericLFI_BODY`.
- 10:30 — browser console confirms the 403; root cause is WAF, not the
  application.
- Later the same day — repo-wide audit of all body-bearing public routes and
  a fix plan (two path sets with body-rule Count overrides, drift-prevention
  test, redacted WAF logging, actionable 403 UI).

## Contributing factors

- The WAF body policy and the public API contract evolved independently; no
  CI check mapped new public write routes to a WAF classification, so routes
  silently inherited full CRS body inspection.
- CRS body signatures are tuned for attack payloads; academic text
  legitimately contains path-, URL-, and code-like tokens, making body
  content inspection a false-positive source on free-text routes.
- WAF logging was disabled and request sampling is intentionally off because
  requests carry the origin secret, so edge-side evidence took manual metric
  correlation to reconstruct.
- The frontend discarded the 403's context: `toApiError` had no business
  `code` for a non-JSON WAF response, and the selection preview rendered a
  duplicated generic title instead of an actionable message.

## Resolution and recovery

No service recovery was needed; the WAF continued to protect all other
traffic throughout. Resolution is the repo-wide fix delivered in the same
change set as ADR 0027: two explicit path scopes where free-text content
routes run the five CRS body rules in Count mode while query-string inspection
stays enforced;
a deployment-contract drift test that classifies every body-bearing public
write route; template-owned WAF logging to CloudWatch Logs with origin and
auth headers redacted; and an `edge_blocked` reader error state with an
actionable explanation. Deployment follows the ordinary immutable release
process; no migration is involved.

## Corrective actions

- WAF template: `ContentFreeTextPathSet` plus Or-scoped rules with
  `RuleActionOverrides` for the body content rules
  (`deploy/ecs/scholens-production.yml`).
- Drift prevention: `test_waf_free_text_path_sets_classify_every_public_write_route`
  cross-checks the committed OpenAPI snapshot against both path sets and the
  structured whitelist (`server/tests/test_deployment_contract.py`).
- Filtered WAF Block/Count logging to `aws-waf-logs-scholens-production`, with
  sensitive headers redacted and request bodies substituted.
- Reader: codeless 403 → `edge_blocked` state with en/zh copy; unit test and
  Storybook coverage.
- Minimal IAM additions to the runtime CloudFormation role for WAF logging
  configuration and log delivery, scoped per AWS's documented permission set.
- Documentation: `deploy/ecs/README.md`, the observability operations doc,
  and ADR 0027.
