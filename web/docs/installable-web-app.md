# Installable Web App

Scholens is distributed on phones as the canonical Next.js Web product. A
researcher can add it to the iOS or Android Home Screen and run it with
`display: standalone`; the installed launch is not a second frontend, native
container, or separate account surface.

## Supported delivery

- iOS Safari uses Share → Add to Home Screen.
- Android Chrome, Edge, and Samsung Internet use the browser installation event
  when it is available and browser-menu instructions otherwise.
- WeChat's in-app browser receives instructions for continuing in the system
  browser rather than a simulated or unsupported install prompt.
- Desktop and unrecognized mobile browsers keep the complete browser product
  without an install control.

The Manifest owns `/` as its `id`, `start_url`, and `scope`, uses standalone
display without locking orientation, and publishes 192 px, 512 px, Apple Touch,
favicon, Android maskable, and monochrome artwork. Light and Dark browser theme
colors come from the generated semantic token metadata; the selected raven
master remains in `web/brand/source/`, and committed runtime exports live under
`web/public/brand/`.

## Installation experience

`features/install-experience` owns platform detection, the Chromium
`beforeinstallprompt` adapter, installed-mode detection, one-time promotion
state, instructions, and the first-installed-launch sign-in hint.

The automatic card becomes eligible only after one accepted Conversation turn
or the first successfully loaded Reader document. Rendering, dismissing, or
acting on the card records the versioned promotion marker. The mobile navigation
retains an Install Scholens entry until standalone mode or `appinstalled` proves
installation. Reader's first mobile PDF hint takes priority, so the reflow hint
and install card never compete for the same lower viewport.

Local flags contain only versioned booleans:

- `scholens:pwa-install-promotion:v1`
- `scholens:pwa-first-launch:v1`
- `scholens:reader-mobile-reflow-nudge:v1`

They contain no actor, paper, query, timeline, or analytics data.

## Network and storage boundary

`/sw.js` is release-versioned, root-scoped, and registered after the page load
event. Its fetch handler is network-only. It does not open the Cache API and
never stores HTML, RSC payloads, APIs, PDFs, signed URLs, translations, searches,
or account data. A failed top-level navigation receives a static bilingual
offline explanation with no user content.

An installed iOS Web App can have storage and cookies isolated from Safari.
Scholens therefore keeps the existing memory access token and secure host-only
refresh cookie contract, explains the one-time installed sign-in, and never
copies tokens between browser contexts.

Zotero authorization is server-bound to its pending request token. An installed
launch prepares the system-browser window during the initiating click, completes
OAuth there, keeps the installed Scholens session alive, and refreshes Zotero
state when the researcher returns. Ordinary browser launches retain same-tab
authorization and the callback result route.

## Deferred capabilities

Push, badges, background sync, offline paper reading, Capacitor/native
containers, and App Store or Play Store distribution are not part of this
boundary. Each requires its own event, privacy, update, and failure contract
before implementation.

## Acceptance

- Unit tests own platform resolution, standalone detection, versioned markers,
  Manifest shape, service-worker headers, cache exclusion, and installed OAuth
  navigation.
- Storybook owns iOS promotion, Android instructions, WeChat guidance, Reader
  reflow guidance, narrow widths, both locales, and Light/Dark appearance.
- Playwright owns the Android install event, Manifest delivery, bilingual
  offline navigation, and installed first-sign-in explanation.
- Release acceptance still includes one physical iPhone and one physical
  Android pass for Home Screen installation, safe areas, keyboards, rotation,
  process restart, file upload, and Zotero authorization.
