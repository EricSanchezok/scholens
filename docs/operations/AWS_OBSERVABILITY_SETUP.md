# AWS observability operations

Scholens production observability is part of the canonical ECS stacks; there is
no separately installed host agent or EC2 observability stack. The current
architecture and release runbook live in
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
