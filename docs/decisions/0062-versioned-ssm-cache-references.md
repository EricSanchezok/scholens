# 0062 — Versioned SSM cache credential references

Status: Accepted
Date: 2026-11-16
Owners: Scholens deployment

## Problem

The private cache uses stable API and Jobs credentials while Secrets Manager
charges for retaining their source objects. Standard Parameter Store can retain
these small values under the existing configuration CMK. Moving the storage
reference must preserve credential bytes, existing ACLs, product role boundaries,
and a usable application rollback.

## Decision

Scholens owns individually versioned Standard `SecureString` parameters, one per
known source field. The source-version identifier is part of each parameter path.
A controlled operator transfers and validates values without putting plaintext,
lengths or value hashes in source, commands, artifacts or logs. Creating a copy
does not authorize changing consumers or deleting the source.

Native CloudFormation does not support `SecureString` parameter resources.
The controlled provisioning manifest records non-secret names, source versions,
CMK identity and verification outcomes. CloudFormation owns only the parameter
ARN inputs, narrowly scoped execution-role reads and consumer references.
Keep the same CMK. Do not add parameter tags to bypass an access condition.

API/conversation and background workers select sources independently through
reviewed plans. Ordinary releases preserve deployed choices and references.
Source-mode parameters are bound to the rendered template, so a manual parameter
edit cannot mislabel the actual credential source. The first render uses Secrets
Manager. Preserve source objects and their existing permissions through rollout
and supported rollback; retirement is a separately reviewed operation.

Valkey retains its existing TLS, ACL, image and persistent-data contracts. Its
reference-only restart is a separate stage after persistence and drain checks.
The current deployment runbooks remain the authority for exact operations.

## Alternatives considered

- Replacing a Secrets Manager JSON ARN with a single Parameter Store ARN would
  change JSON-field injection semantics. Select and validate each field instead.
- A CloudFormation custom resource handling values would introduce another
  principal and a payload-bearing lifecycle. Keep the value operation outside
  the template and grant only reviewed consumer reads.
- Switching all readers and deleting sources together would remove the verified
  rollback before end-to-end acceptance.
- Moving to the default Parameter Store key would change the encryption-control
  boundary; retain the existing product CMK for this migration.

## Consequences

The deployment inventory must retain the source-version-to-parameter mapping.
Future credential changes require a new controlled copy and a coordinated reader
rollout; Parameter Store does not supply Secrets Manager rotation automatically.
The current sources have no automatic rotation configured. Duplicating values
alone saves no Secrets Manager storage fee and does not retire the CMK.

## Validation

Deployment tests assert exact-resource reads, unchanged source permissions and
trust, independent API/Jobs selection, default preservation, rejected partial or
foreign references, and unchanged non-cache task properties. Production acceptance
must separately confirm both ACL identities, cross-prefix denial, service health,
worker registration recovery and retained important alarms.
