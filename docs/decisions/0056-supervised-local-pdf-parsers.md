# 0056 — Supervised local PDF parsers

Status: Accepted
Date: 2026-09-27
Owners: Scholens Jobs

## Problem

Cancelling `asyncio.to_thread` does not stop native parser work. A timed-out
primary parser could overlap its fallback and retain CPU and memory, and the
event-loop shutdown could still wait for the original thread. This makes the
single-host admission budget and the claimed parser deadline unreliable.

Preview generation also allocated a two-times full-page raster before shrinking
it, so a physically large page could exhaust memory for a small thumbnail.

## Decision

Run local analysis and each extraction attempt in its own supervised subprocess.
Use private source/result files with explicit size ceilings instead of passing
PDF bytes or unbounded output through pipes. The parent terminates and reaps the
process group on timeout or cancellation before choosing a fallback. Linux
parent-death signalling covers a hard-killed owning Celery child. No provider or
storage credentials are needed by the parser protocol. Parse libraries load
only in the process that uses them.

Set preview dimensions before raster allocation, preserve the page aspect ratio,
and transfer RGB samples directly into the WebP encoder. Retain the existing
text-quality policy, source hash, exact page offsets and MinerU rescue boundary.

## Alternatives considered

- Thread cancellation cannot release native resources or enforce a deadline.
- A persistent multiprocessing pool cannot reliably replace just one stuck
  native parser and cannot be created normally inside a daemon Celery child.
- Increasing container memory would hide overlap without correcting ownership.

## Consequences

Each attempt pays interpreter/import startup overhead. In exchange, native
memory is released at the stage boundary and timeout has an enforceable owner.
Result serialization has a bounded additional copy; source files are reused.
The design requires POSIX process groups and Linux production parent-death
support, matching the deployed worker runtime. Remote OCR retains its own
deadline and durable provider checkpoint.

## Validation

Exercise an uncooperative process that ignores SIGTERM, cancellation during an
active parse, real local extraction and all existing fallback/quality tests.
Render a 14,400-point page and verify its preview remains within the pixel bound.
Measure process peaks on the production architecture before reducing hard
limits; successful termination alone is not a memory-sizing benchmark.
