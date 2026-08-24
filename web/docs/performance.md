# Web Performance

Scholens treats perceived responsiveness and eventual completion as separate
contracts. A navigation must acknowledge the input immediately even when a
dynamic route, authentication, or a remote API still needs a network round
trip. Full-page transition animation is not part of that contract.

The installable Web App registers its root-scoped Service Worker after the load
event so installation support does not delay the initial render. The worker is
network-only and adds no runtime or storage cache; it supplies only a static
bilingual document when a top-level navigation fails offline. Service-worker
updates bypass the HTTP cache and use the release SHA embedded in `/sw.js`.

## Navigation

The persistent Workspace destinations use Next.js `Link` prefetching and
`useLinkStatus`. Pressed styling is immediate; the pending destination receives
a stable visual indicator and an accessible status while the current route
remains interruptible. `app/loading.tsx` is the dynamic-route fallback and must
stay free of product data or simulated success content.

Route performance is measured from the accepted click to the next painted
feedback, committed route, and primary product content. The targets are:

- interaction feedback p75 at or below 100 ms and p95 at or below 200 ms;
- INP p75 at or below 200 ms for mobile and desktop;
- non-China warm primary content p75 at or below 1 second and p95 at or below
  2 seconds;
- non-China cold shell p75 at or below 1.5 seconds and primary Library content
  p75 at or below 2.5 seconds.

## Real-user measurement

`WebPerformanceReporter` sends Core Web Vitals, the three navigation
milestones, and Conversation interaction milestones to the same-origin
`POST /__telemetry/web-performance` Web route. Conversation measurements cover
painted submit feedback, durable acceptance, first SSE event, first visible
answer content, ready, and the longest event stall. A tracker reports each
milestone at most once for one submission.

The strict union contract accepts only a release, metric, duration/value,
coarse route group, device class, Network Information category, Save-Data flag,
rating, random event ID, and optional direct-or-resume stream kind. It never
accepts a user/account/Conversation identifier, content, title, query string,
raw URL, or IP address. The receiver adds only `CN`/`non-CN` and the Cloudflare
colo, writes structured `web_performance` or `conversation_performance` events,
and returns `204` without persistence in application state.

The production CloudWatch dashboard calculates p75, p95, and sample counts by
metric, route, device, and country group from the Web log group. Mainland CDN
or acceleration procurement begins only after two consecutive weeks show that
non-China targets pass while China mobile primary-content p75 is both above
1.5 seconds and more than twice the non-China value.

## Conversation streaming

Submitting a prompt must publish local feedback within 100 ms at p75 and 200 ms
at p95. The browser keeps every decoded event in the target state, but ordinary
answer deltas reach React at most once per 50 ms and align to the next animation
frame while the document is visible. Terminal, cancellation, error, and reset
events bypass that cadence. Hidden documents use a bounded timer so a suspended
animation frame cannot accumulate an unbounded event array.

Only the active assistant answer and worklog subscribe to live state. Historical
messages, Workspace navigation, and Reader pages must retain stable props while
tokens arrive. Streaming Markdown may use a deferred value; canonical terminal
content renders without an artificial typewriter or smoothing delay. A 40-second
no-byte watchdog initiates resumable reconnection, while online and visibility
changes retry immediately. These are deterministic client invariants; provider
first-token time and tool pauses remain separately observable service latency.

## Verification

Performance changes retain deterministic unit, Storybook, and Playwright
behavior. Production bundle comparisons use the procedure in
[`testing.md`](./testing.md); local development timings are evidence for
regression diagnosis, not production acceptance. Do not add arbitrary sleeps,
route transitions, raw timing tokens, or speculative caching to make a test or
demo appear faster.
