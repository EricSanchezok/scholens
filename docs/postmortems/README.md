# Postmortems

Postmortems capture learning from an incident whose impact or recurrence shows
that a local bug report is not enough. They are factual, blameless records that
connect impact and contributing conditions to owned corrective actions.

Write a postmortem for:

- production or shared-development data loss, corruption, privacy, or security
  exposure;
- a failed deployment or rollback, material service interruption, or broken
  release safety control;
- a repeated regression that demonstrates a systemic gap in tests, review,
  design governance, or ownership;
- an incident that crossed service boundaries or required non-obvious recovery.

Do not write one for an isolated low-impact defect with a clear local fix, a
planned architecture choice, or ordinary pull-request review. Use an ADR for a
durable decision and the pull request for normal implementation history.

Name records `YYYY-MM-DD-short-incident-name.md`. Keep secrets, personal data,
raw credentials, and sensitive customer content out of the repository. A
postmortem may link to restricted operational evidence without copying it.

## Template

```markdown
# Incident title

- Date: YYYY-MM-DD
- Status: Draft | Final
- Severity: SEV-1 | SEV-2 | SEV-3
- Owners: names or team

## Summary

What happened and how the incident ended.

## Impact

Who or what was affected, for how long, and what was not affected.

## Detection

How the incident was discovered and why existing signals did or did not help.

## Timeline

Key events and decisions in chronological order, with time zones.

## Contributing factors

Technical and process conditions that allowed the incident; avoid individual
blame and unsupported root-cause claims.

## Resolution and recovery

How service or data was restored and how recovery was verified.

## Corrective actions

| Action                                       | Owner | Status | Tracking link |
| -------------------------------------------- | ----- | ------ | ------------- |
| Concrete preventive or detection improvement | team  | Open   | issue or PR   |

## Lessons

What should be preserved, changed, or reconsidered.
```

Corrective actions belong in tracked issues or pull requests and must name an
owner. Update the postmortem only to correct facts or reflect action status; do
not turn it into the current architecture or operations manual.
