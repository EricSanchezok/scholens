# 0015 — Durable Reader selection translation

Status: Accepted
Date: 2026-08-14
Owners: Scholens

## Context

Reader already produced normalized PDF selections for Ask and annotations, but
translation was absent from the replacement frontend. A short-lived Redis
result cache would make completed work disappear, couple product data to an
operational service, and charge concurrent identical requests more than once.
Tying translation language to the interface locale would also make bilingual
reading unpredictable.

## Decision

Reader translation is a vertical feature slice. The PDF remains the canonical
and default document view. Selection translation consumes the existing typed
`PaperSelectionTurnContext`, waits 300 ms for automatic selection stability,
and cancels stale browser requests. Desktop may show a compact anchored preview;
narrow screens open the existing full-height contextual Sheet. The complete
panel owns language direction, automatic-selection preference, custom
instructions, streaming feedback, copy, retry, and annotation handoff.

The public API is deliberately specific:

- `GET|PUT /api/v1/me/translation-preferences`;
- `POST /api/v1/papers/{document_id}/selection-translations` as standard SSE.

PostgreSQL owns completed translation results without an expiry. The identity
is a SHA-256 digest over document, normalized source, title hash, source and
target languages, instruction hash, prompt revision, and provider-neutral AI
profile revision. The row stores translated text and hashes, never raw source
text. A Document deletion cascades its results.

Redis owns only per-user/per-IP rate checks, concurrent-capacity leases, and a
short single-flight lease. Paper authorization runs before result lookup. A
cache hit skips Token Credit and provider-capacity checks. An identical request
that does not hold the single-flight lease waits for the first durable result
and never starts a second charged model call.

Provider invocation uses the shared `translation` AI runtime profile. Product
contracts contain no DeepSeek-specific field, endpoint, or model name. Source
and target language preferences are content settings and do not derive from
the interface locale; the default target is `zh-CN`.

## Alternatives considered

- Keep completed translations in Redis with a TTL. Rejected because useful
  product data would expire and operational eviction would change behavior.
- Store source text with the result. Rejected because the document already owns
  the source and the cache needs only a collision-resistant identity.
- Reuse the conversation streaming reducer. Rejected because translation is a
  content transformation with a smaller terminal protocol, not a conversation.
- Infer target language from UI locale. Rejected because UI and paper-content
  languages are independent user choices.
- Add a legacy `/translations` alias. Rejected because the product is
  pre-release and the alias would become dead compatibility surface.

## Consequences

The translation result store opens its own short transaction because SSE work
outlives the request-scoped transaction. The browser and server share one
generic SSE framing utility, while each feature validates its own event payload.
Changing a language, instruction, prompt, or AI-profile revision intentionally
creates another durable result. Quota exhaustion still permits authorized cache
hits.

## Validation

Server tests cover preference normalization, authorization-before-cache,
single-flight release, quota bypass on hits, provider failures, cancellation,
and source-text-free persistence. Web unit tests cover SSE validation, the
300 ms stability delay, and stale-request abortion. Storybook covers idle,
ready, streaming, completed/cached, quota, retry, narrow mobile, and Dark states
with automated accessibility checks. Manual browser review verifies desktop
preview placement, mobile containment, and Dark token resolution.
