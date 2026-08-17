## Summary

<!-- What changed, why it changed, and the user-visible outcome. -->

## Scope and impact

Mark every applicable item and explain the impact below. Use “None” when the
area was reviewed and is unaffected.

- [ ] Public API / OpenAPI contract
- [ ] `scholens` database schema or data ownership
- [ ] Shared Python package contract or dependency direction
- [ ] Product behavior or terminology
- [ ] Documentation or ADR
- [ ] Visual design, responsive behavior, or accessibility
- [ ] Deployment, runtime configuration, or release behavior
- [ ] No impact in the areas above

Impact notes:

<!--
API:
Database:
Packages:
Documentation / ADR:
Visual / accessibility:
Deployment / release:
-->

Contract evolution class (required when API, MCP, jobs, or schema is affected):

- [ ] Internal — no stored-data or published-contract change
- [ ] Compatible — additive for every supported consumer/application revision
- [ ] Deprecated — exact target, replacement, owner, telemetry key, and removal
      dates recorded
- [ ] Contract — prior rollout/backfill, compatibility floor, and recovery
      evidence recorded
- [ ] Not applicable

## Verification

List the exact commands that were executed. Do not write “CI” or “tests pass”
without naming the gate or targeted command.

```text
./scripts/run-gates.sh <lane>
```

Manual or visual verification:

<!-- Include routes, viewports, themes, locales, and interaction states. -->

## Delivery notes

- [ ] Generated artifacts changed with their source, or are not applicable
- [ ] Public v1 and applied-migration compatibility gates pass, or are not
      applicable
- [ ] Temporary compatibility is boundary-local and has an owner and removal condition
- [ ] Schema work identifies expand, migrate/switch, or contract phase and
      preserves production data
- [ ] Documentation impact was handled in this PR
- [ ] This PR does not install dependencies, migrate data, or publish as a side effect
- [ ] Rollout, rollback, or follow-up work is recorded when deployment is affected
