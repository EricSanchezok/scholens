# Scholens Storage

Server and Jobs use `AsyncS3Storage` for finite object reads and bounded cleanup.
The package owns only transfer mechanics. Applications supply the bucket, region,
byte bound and cleanup prefixes; authorization and job leases stay in Server.

Every operation owns a fresh async S3 client inside a total deadline, including
credential lookup, retries, headers and body transfer. Cancellation closes the
body and client before control returns. Slow trickles cannot extend the deadline.
No signed URLs are created or logged. There is no global event-loop-bound client.
Synchronous worker threads call `asyncio.run`; async effects await the operation
directly, so they never leave a detached blocking S3 thread after cancellation.

Reads require an explicit byte limit. Downloads use bounded chunks and remove a
partial destination on failure. Cleanup accepts one page per explicit prefix,
checks every returned key against its prefix and returns whether all pages were
exhausted. It does not invent prefixes or retry a whole page after the deadline.

The SDK's standard credential and endpoint provider chain is retained. Consumer
lockfiles pin compatible boto3, botocore and aiobotocore versions together.
