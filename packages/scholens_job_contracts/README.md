# Scholens job contracts

`scholens_job_contracts` owns the narrow, service-neutral contracts that Server and
Jobs must interpret identically:

- the closed set of background queue names used by outbox dispatch, Celery routing,
  and predefined SQS queues; and
- the Zotero completion handoff timing margins: heartbeat, Server processing bound,
  Jobs HTTP timeout, and renewable callback lease.

The timing values live in their own `zotero` module; `queues` remains limited to queue
identity. The package owns no broker, persistence, HTTP implementation, or product
workflow code.
