# Scholens job contracts

`scholens_job_contracts` is the single shared contract for background queue names.
Server imports it when persisting an outbox dispatch and Jobs imports it when declaring
Celery routes and predefined SQS queues. It owns no broker, persistence, or workflow code.
