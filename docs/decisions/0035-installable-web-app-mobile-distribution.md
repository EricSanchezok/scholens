# 0035 — Installable Web App as the first mobile distribution boundary

Status: Accepted
Date: 2026-08-20
Owners: Scholens Web

## Problem

Scholens already has one responsive canonical Web frontend, but mobile browser
chrome, changing visual viewports, and in-app browsers make repeated phone use
feel less stable than an application. Shipping separate iOS and Android clients
now would duplicate authentication, Reader, Conversation, Library, release, and
quality contracts before platform-specific capability justifies that cost.

Installation also creates privacy and lifecycle questions. Research papers,
signed URLs, conversations, and derived content are sensitive; a generic PWA
cache must not turn installation into uncontrolled offline persistence. iOS may
isolate an installed Web App's cookies and storage from Safari, and external
Zotero OAuth must not destroy the installed app's authenticated context.

## Decision

The canonical `web/` product is Scholens's first mobile distribution boundary.
It publishes a standards-based Manifest, app artwork, standalone display, and a
root Service Worker for iOS Safari and Android Chrome, Edge, and Samsung
Internet. Scholens detects WeChat's in-app browser and explains how to continue
in the system browser.

The Service Worker is strictly network-only. It never caches authorized or
research content and responds to a failed top-level navigation with a static,
bilingual, user-data-free offline page. Push, background sync, and offline paper
reading are outside this decision.

Installation is promoted once only after an accepted Conversation turn or a
successfully loaded Reader paper. A permanent mobile navigation entry remains
until installation. Installed anonymous launches explain the one-time local
sign-in without migrating credentials. Installed Zotero OAuth keeps the app
alive while the provider opens in the system browser and refreshes durable
connection state on return.

## Alternatives considered

- Build native Swift and Kotlin clients now. Rejected because it duplicates the
  complete product and release surface without a current native-only outcome.
- Wrap the Web product in Capacitor immediately. Rejected because store review,
  deep links, OAuth, binary releases, and native bridge ownership add a second
  delivery boundary before the installable Web product is measured.
- Cache the application shell and recent papers for offline reading. Rejected
  because authenticated RSC, signed resources, storage quotas, revocation, and
  research-data deletion need a separate explicit design.
- Use an install-only Manifest without a Service Worker. Rejected because a safe
  offline navigation response and deterministic update boundary materially
  improve installed launch behavior without caching product data.

## Consequences

Mobile browser and installed launches share one feature implementation and
deployment boundary. The Web team owns Manifest compatibility, icons,
standalone safe areas, install guidance, service-worker updates, and physical
iOS/Android acceptance. Users may need to sign in once inside an installed iOS
launch and must reconnect before accessing any research after an offline cold
start.

A future native container or store listing must justify its native-only
outcomes and record a new boundary. Push and offline paper access likewise need
separate event, consent, retention, revocation, quota, and failure contracts.

## Validation

CI validates Manifest shape, artwork declarations, service-worker headers and
cache exclusion, platform and standalone detection, one-time prompts, installed
OAuth navigation, Android install events, offline cold navigation, and the
installed sign-in explanation. Release acceptance adds physical iPhone and
Android installation, restart, safe-area, keyboard, rotation, upload, and
Zotero authorization checks.
