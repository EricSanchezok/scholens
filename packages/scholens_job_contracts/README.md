# Scholens job contracts

`scholens_job_contracts` owns the narrow, service-neutral contracts that Server and
Jobs must interpret identically:

- the closed set of background queue names used by outbox dispatch, Celery routing,
  and predefined SQS queues; and
- the Zotero completion handoff timing margins: heartbeat, Server processing bound,
  Jobs HTTP timeout, and renewable callback lease; and
- the aggregate Zotero callback byte ceiling plus the annotation/automatic-import
  budget split that both services must enforce; and
- the aggregate Jobs callback body ceiling plus parser-controlled PDF text and
  page-map ceilings that Jobs and Server validate using the exact wire encoding;
  and
- the consumer-first `repair_pdf_text` task name and exact JSON-safe kwargs used
  for targeted canonical PDF text repair; and
- the Unicode replacement marker, stable warning, retry ceiling, and
  deterministic content-ratio/evidence policy used to compare extracted PDF
  text candidates before either service accepts a replacement; and
- the generated-object deletion allowlist, strict producer ordering and
  uniqueness rule, 1,024-byte key ceiling, 100-key batch ceiling, and 64 KiB
  encoded key-payload ceiling enforced by both the Server producer and Jobs
  consumer.

The common callback values live in `callbacks`, Zotero-specific values live in
`zotero`, the repair envelope lives in `pdf_repair`, the pure comparison policy
lives in `pdf_quality`, generated-object deletion payload rules live in
`storage_cleanup`, and `queues` remains limited to queue identity. The package
owns no parser model, broker, persistence, HTTP implementation, or product
workflow code.
