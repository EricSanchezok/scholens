# ADR 0056: Opt-out egress address policy for local proxy development

- Status: Accepted
- Date: 2026-09-18
- Owners: Scholens maintainers
- Scope: Jobs source downloads and Zotero attachment downloads

## Problem

Outbound source downloads require every DNS answer and the connected peer to
be a global unicast address, which blocks server-side request forgery. Local
proxy DNS in fake-ip mode (Clash/OpenClash) answers public hosts with
synthetic addresses from 198.18.0.0/15, which the guard classifies as
non-public. arXiv ingestion therefore fails with
`paper_source_unsafe_address` on such machines while uploads keep working,
because uploads never leave the storage path.

## Decision

Keep the strict public-address requirement as the default for every outbound
source download. Introduce one explicit opt-out,
`ALLOW_NON_PUBLIC_SOURCE_ADDRESSES=1` in `jobs/.env`, that skips only the
address-policy checks in `tasks` and `zotero`. Structural failures (empty DNS
answers, missing peer addresses) and every other guard remain active. The
opt-out is documented as local-only; no deployment sets it.

## Alternatives considered

- Remove the guard: turns a local development obstacle into a production SSRF
  regression.
- Per-host allowlist: requires maintaining a list of public scholarly hosts
  and still fails for every unlisted host behind the proxy.
- Resolve real addresses inside the worker (DoH or proxy-aware resolution):
  adds a second resolution path that can disagree with the proxy and adds
  moving parts for a development-only problem.

## Consequences

Local development behind fake-ip proxies can ingest arXiv, DOI, and URL
sources again, and the Zotero attachment path stays usable on the same
machines. The guard's production behavior is unchanged, and the single flag
keeps the policy in one place. If a future proxy mode answers real addresses,
the flag becomes unnecessary and can be removed.

## Validation

`jobs` unit tests cover both modes: the default rejects a fake-ip DNS answer
with `paper_source_unsafe_address`, and the opt-out completes a download that
resolves and connects through a non-public address. `.env.example` documents
the flag with an empty (strict) default.
