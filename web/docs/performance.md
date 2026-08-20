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

`WebPerformanceReporter` sends Core Web Vitals plus the three navigation
milestones to the same-origin `POST /__telemetry/web-performance` Web route.
The contract accepts only a release, metric, duration/value, coarse route
group, device class, Network Information category, Save-Data flag, rating, and
random event ID. It never accepts a user/account identifier, content title,
query string, raw URL, or IP address. The receiver adds only `CN`/`non-CN` and
the Cloudflare colo, writes structured `web_performance` events, and returns
`204` without persistence in application state.

The production CloudWatch dashboard calculates p75, p95, and sample counts by
metric, route, device, and country group from the Web log group. Mainland CDN
or acceleration procurement begins only after two consecutive weeks show that
non-China targets pass while China mobile primary-content p75 is both above
1.5 seconds and more than twice the non-China value.

## Verification

Performance changes retain deterministic unit, Storybook, and Playwright
behavior. Production bundle comparisons use the procedure in
[`testing.md`](./testing.md); local development timings are evidence for
regression diagnosis, not production acceptance. Do not add arbitrary sleeps,
route transitions, raw timing tokens, or speculative caching to make a test or
demo appear faster.
