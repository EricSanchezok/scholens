# Valkey credential references

`runtime.yml` owns the existing single-instance private Valkey service and its
ECS execution role. `CacheCredentialSource=secretsmanager` is the default for a
new stack and preserves the original two JSON-field references. Ordinary stack
updates must preserve all deployed parameter values, including this selection;
never let an omitted operator input reset a previously selected source.

For a reviewed SSM migration, supply the exact nonsecret
`ApiCachePasswordParameterArn` and `JobsCachePasswordParameterArn` together.
Each identifies one version-named, product-owned Standard `SecureString`
parameter in the personal account and region. The parameter values must already
match the original passwords, have passed the 4 KiB UTF-8 limit and have been
verified inside the approved transfer process. Do not put values in a template,
command argument, artifact or log. This template creates no parameter or secret.

With both ARNs configured, the execution role additionally receives
`ssm:GetParameters` for only those two ARNs and `kms:Decrypt` on the existing
configuration CMK, restricted to the regional SSM service and those exact
`PARAMETER_ARN` encryption contexts. The original Secrets Manager grants remain.
There is no application task role, new trusted principal, key-policy change,
password rotation or ACL change. The explicit `ssm` selection changes only the
two `CACHE_*_PASSWORD` references to whole SSM parameter ARNs; SSM references do
not use Secrets Manager JSON-key or version suffix syntax.

## Staged change and acceptance

1. Keep the old secret ARNs, current versions, compatible image, mounted
   configuration and current template/parameters for rollback. Confirm current
   AOF/RDB health and recovery evidence without printing values. A template
   alone does not prove the live persistence state.
2. Review the exact CloudFormation change set. Configuring both parameter ARNs
   while retaining `secretsmanager` permits a permission-only stage at the
   resolved-resource level. Inspect the real change set rather than assuming
   that CloudFormation will avoid task-definition replacement.
3. Before selecting `ssm`, pause new product background admission and safely
   drain in-flight work through the existing product controls. Do not kill or
   replay jobs. The service has one fixed-port replica with minimum healthy
   zero / maximum one hundred percent, so replacement has an unavailable
   interval; it is not a zero-downtime deployment.
4. Apply only the reviewed role/reference changes after the recovery gate and
   accepted restart window. Keep the same image, TLS, ACL, memory bounds,
   network/port, logs and host data mount. Do not run `prepare-host.sh` or
   rewrite the mounted bootstrap/configuration for this reference-only change.
5. Verify the new task is healthy, both approved identities can authenticate
   and perform their permitted operations, and cross-prefix access is denied.
   The existing TLS/NOAUTH health check proves only listener/authentication
   presence. Verify dependent consumers and important alarms before restoring
   the recorded background enable flags. Record observed interruption and
   convergence times separately from the planning estimate.

If injection, startup or acceptance fails, stop the rollout and prepare a new
exact change set selecting `secretsmanager` with the original password
references and compatible image. Keep the same host data directory; task
rollback does not repair damaged host configuration or data. Restore healthy
consumers before removing the added SSM grants. Clearing both parameter ARNs
after the source has returned to `secretsmanager` removes those grants; clearing
only one is rejected. No cleanup of old secrets, parameters, keys, AOF or RDB is
part of this migration. Retaining the original sources keeps copy/canary stages
from reducing Secrets Manager storage fees.
