# Scholens job contracts

`scholens_job_contracts` owns the narrow, service-neutral contracts that Server and
Jobs must interpret identically:

- the closed set of background queue names used by outbox dispatch, Celery routing,
  and predefined SQS queues; and
- the Zotero completion handoff timing margins: heartbeat, Server processing bound,
  Jobs HTTP timeout, and renewable callback lease; and
- the aggregate Zotero callback byte ceiling plus the annotation/automatic-import
  budget split that both services must enforce.

The Zotero values live in their own `zotero` module; `queues` remains limited to queue
identity. The package owns no broker, persistence, HTTP implementation, or product
workflow code.
