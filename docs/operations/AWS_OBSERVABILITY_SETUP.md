# AWS observability operations

Scholens currently runs on the shared personal EC2 host. Its topology and release
runbook live in [`deploy/personal/README.md`](../../deploy/personal/README.md).
The personal adapter removes the managed topology's ALB, ADOT sidecars, X-Ray
export and dashboard. In-process OpenTelemetry calls alone do not establish a
working metrics export. A missing `Scholens/Production` series is unavailable
evidence, not zero failures.

## Personal production

Application stdout reaches CloudWatch through ECS `awslogs`. Runtime log groups
retain 30 days for incident review and the contract retirement observation
window. The separately reviewed `application-monitoring.yml` stack derives
16 fixed metric names in `Scholens/Personal` from these existing logs, without an
exporter process or additional application permissions. Metric dimensions never
contain users, jobs, documents, model revisions, or request references. These
custom metrics and fourteen alarms have CloudWatch charges; they add no host tier.
Only the two durable-backlog metrics have a dimension: `Queue`, restricted by
the filter to the six registered queue names. This bounds the total to 26 metric
series. All other metrics remain dimensionless.

HTTP completion logs, metrics and matched-route spans use the complete registered
route template, including every router prefix and named parameter. FastAPI 0.138's
public route-context iterator supplies those templates; the leaf route's `path`
alone can omit `/api/v1` or `/internal/v1`. The HTTP adapter compiles a per-application
catalog once after route composition, disambiguates repeated router inclusions by
the matched path, and removes an ASGI deployment root before matching. The catalog
stores no request paths or identities. Reading-activity suppression remains in
force. Verify nested success, error and method-rejected routes when upgrading the
framework, since losing a prefix can silently stop receipt-latency samples.

| Signal | Source and interpretation |
|---|---|
| `HttpRequests`, `HttpServerErrors`, `HttpStreamFailures` | Logged HTTP completions; privacy-suppressed reading endpoints are not included. Counts are not a universal request denominator. |
| `HttpHealthChecks` | Successful `/livez` completions. Five consecutive missing minutes alert on either API availability or broken log delivery. |
| `McpInternalErrors`, `McpResultBudgetErrors` | Typed MCP error envelopes, including failures returned over HTTP 200. Authentication/permission mistakes are excluded from the internal-error alarm. |
| `ResultReceiptDuration` | Successful normalized `/internal/v1/jobs/{job_id}/results` requests, in milliseconds. p95 above one second for two populated five-minute periods alerts; sparse percentiles do not trigger it. |
| `ResultConsumerFailures` | Result application, durable effect or consumer failures. Three failures within five minutes alert; the count is attempts, not unique failed jobs. |
| `JobExecutions`, `JobFailures` | Exactly one `job.task.completed` record per execution in the five admitted worker groups. Retries/redeliveries are executions, not unique document imports. Three failures within five minutes alert. |
| `InferenceQueryDuration`, `InferenceFailedResponses` | Completed socket responses. Health probes are excluded; disconnected clients produce no completion, so these metrics cannot measure all client-side fallbacks. |
| `DurablePendingJobs`, `DurableOldestPendingSeconds` | One scalar PostgreSQL aggregation per minute, with explicit zeroes for empty queues. Counts every accepted pending job, including unpublished, retrying and broker-published work; running and terminal jobs are excluded. Six fixed queue series alert after three consecutive minutes above 60 seconds for conversation, 120 for document, and 1,800 for the remaining queues. |
| `DurableQueueObservations`, `DurableQueueObservationFailures` | A success heartbeat follows all six snapshot records. Database failure emits only a redacted failure event, never a healthy zero. Five missing minutes or three failures within five minutes alert. |

HTTP server errors and internal/unavailable MCP errors each alert on one event
within five minutes. All error alarms treat idle missing data as non-breaching.
The health-log and durable-snapshot silence alarms treat missing data as a failure. Counter
filters publish zero when other logs arrive without a matching event; duration
filters never insert synthetic zeros or negative samples. Metric filters process
new log ingestion only, not retained history. See
[AWS metric-filter semantics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/MonitoringLogData.html).

Fair publication deliberately retains backlog in PostgreSQL. An empty SQS queue
therefore cannot establish that every user's accepted work has started. The
existing outbox dispatcher observes durable waiting work off the ASGI event loop,
at most once per minute even while continuously publishing. It reads only queue,
count and oldest acceptance time, with five-second statement and one-second lock
timeouts, and releases the transaction before logging. Observation failure does
not prevent publishing or disclose SQL, job payloads or identities. No additional
process, scheduler, exporter or database migration is required.

After deployment, verify every filter with `aws logs test-metric-filter` using
synthetic positive and negative events; this tests patterns without publishing
fake failures or notifying subscribers. Then confirm actual successful health,
result-receipt and worker events produce samples through `get-metric-statistics`.
Metric listings can lag ingestion. Check the real queue delay/DLQ alarms, host
admission status, available memory, ECS health, and public Web/API together.
Do not interpret an `OK` error alarm with no business traffic as an end-to-end
acceptance result. Use Logs Insights for task names, error codes, stage timings,
and request references; retain private content outside routine logs.

For the first durable-backlog rollout, deploy the application reporter first and
confirm actual `jobs.outbox.backlog` records for all six queues followed by
`jobs.outbox.backlog_observed`. Then execute the reviewed monitoring change set
and verify the new metric samples and alarms. Before rolling back to an
application without this reporter, use a reviewed monitoring change set to
remove its six durable-waiting alarms, snapshot-silence alarm and observation
failure alarm. Keep the existing HTTP, receipt, worker, inference and SQS
monitoring active. Additive filters can remain; missing reporter samples are
unavailable evidence and must never be presented as an empty durable backlog.

The managed-ECS procedures below apply only if that topology is explicitly
deployed again; they are not evidence that personal production has ALB, ADOT,
WAF or X-Ray resources.

## Managed ECS topology

The reference architecture and runbook live in
[`deploy/ecs/README.md`](../../deploy/ecs/README.md).

The foundation stack retains the encrypted diagnostic bucket and KMS key, SNS
alert topic, and MFA-protected diagnostic break-glass role. The runtime stack
owns service log groups, the pinned ADOT sidecars, CloudWatch alarms, and the
`SanchezCloud-Scholens` dashboard. API and worker task roles can write diagnostic
objects but cannot read them; the production deployment role cannot read the
edge origin secret.

## Release checks

After a protected deployment:

1. Confirm every ECS service is stable and both Web and API target groups have
   healthy hosts.
2. Confirm `/sanchezcloud/scholens/web`, `/api`, `/document`, `/research`, and
   `/maintenance` receive structured events for the deployed `RELEASE_SHA`.
3. Confirm the dashboard receives ALB, ECS, SQS, cache, and application metrics.
4. Exercise one successful request and one controlled failure. Correlate the
   response request/diagnostic identifiers with CloudWatch logs and X-Ray.
5. Confirm a diagnostic write lands under the expected release prefix without
   granting the application a read path.
6. Confirm the Web and API unhealthy-host alarms use their own target-group and
   load-balancer dimensions, and that queue age/DLQ alarms publish to the alert
   topic.

Conversation citation resilience is evaluated separately from provider health.
The dashboard should chart `scholens.conversation.answer.completed`,
`scholens.conversation.citation.status`,
`scholens.conversation.citation.grounding`,
`scholens.conversation.citation.repair.success`,
`scholens.conversation.citation.repair.exhausted`,
`scholens.conversation.citation.verifier.timeout`, and
`scholens.conversation.citation.hard_failure` by provider, model profile, and
scope. Keep citation coverage and precision as separate offline/evaluation
series; neither is an availability alarm on its own. A spike in
`unavailable/partial` with stable answer completion is a provenance-quality
incident, while a spike in hard failures or answer completion loss is a
provider/runtime incident.

Before a release and after a rollback, run the redacted offline acceptance set
from the Server workspace:

```bash
cd server
uv run python -m evals.run_citation_resilience_eval
```

The result must keep structural citation precision at `1.0`; coverage is a
separate trend and is not an availability gate. Keep the manifest free of raw
prompts, provider bodies, nonce values, and source identifiers.

For a deprecated HTTP route or MCP tool, confirm the registry's
low-cardinality telemetry key is queryable for the full retirement window.
Removal requires both at least 90 days since notice and production evidence of
30 consecutive days with zero calls. Preserve the dashboard or query reference
in the registry's removal tombstone. For a contract migration, retain the
backfill totals and invariant results, confirm queued work using the retired
shape has drained, and record the deployed application revision before the
compatibility floor advances.

Use only the MFA-protected break-glass role to read a diagnostic snapshot during
an incident. Never place user prompts, document contents, credentials, query
strings, or raw provider responses in metric dimensions or routine logs.

Private browser source maps are published from the same BuildKit graph as the
Web image. Each object is conditionally created under
`source-maps/<release-sha>/`; its checksum and the complete deterministic index
are bound into the immutable release manifest. They are not present in the
runtime image and must not be copied to a public bucket.

Run the side-effect-free deployment contract before operational review:

```bash
./scripts/run-gates.sh deployment
```

Creating or updating either CloudFormation stack, changing Cloudflare, reading
diagnostics, and running protected workflows remain explicit operator actions;
this document does not authorize them.

## WAF logs

The runtime stack streams AWS WAF Block and Count records directly to the
`aws-waf-logs-scholens-production` CloudWatch Logs log group (30-day
retention); ordinary allowed traffic is dropped by the logging filter. The
`x-scholens-origin`, `cookie`, and `authorization` headers are redacted, and
the Web ACL data-protection policy substitutes request bodies. Sampled requests
stay disabled across the Web ACL and its rules; WAF logging and request
sampling are separate controls.

When a request is blocked by the edge before it reaches the API, CloudWatch
Logs Insights against this group is the fastest signal: filter on the request
ID/URI and inspect `terminatingRuleId` and `ruleMatchDetails` plus any
`awswaf:managed:*` labels. The two WAF CloudWatch metrics namespaces
(`scholens-common-threats-standard-body` for structured paths and
`scholens-common-threats-reviewed-large-body` for free-text content paths)
report `BlockedRequests` and `CountedRequests` per managed rule; a
`GenericLFI_Body` count with a COUNT action on a free-text path is the expected
false-positive signature for academic text containing path-like tokens.
