# Settings experience

Settings is the account-level control surface opened from the user menu in the
Workspace shell. Its visual hierarchy follows Figma node `562:4`: a quiet
navigation rail, compact labeled controls, one primary content column, and
semantic status feedback. Code owns responsive behavior, accessibility, and
runtime contracts rather than reproducing fixed Figma coordinates.

## Navigation and responsive structure

Desktop Settings remains shareable URL state in `?settings=`. Supported values
are `general`, `account`, `usage`, `access-keys`, `connections`, and
`translation`; an absent or invalid value closes Settings. Desktop uses a
contained dialog with a quiet navigation rail and one scrolling content
region. Closing the dialog removes only the Settings query parameter and
preserves other workspace state.

Phones use an account center instead of shrinking that dialog. The fourth
workspace destination opens `/me`, whose unboxed identity block, one compact
plan-and-usage summary surface, and divided preference/help groups form the
mobile account overview. Its children are real routes:

- `/me/account` owns read-only identity, Account Center, and current-browser
  Sign out;
- `/me/usage` owns complete plan and resource usage;
- `/me/settings` discloses only Display and interaction plus Translation;
- `/me/settings/display` owns appearance, interface locale, and motion;
- `/me/settings/translation` owns Reader translation preferences;
- `/me/connections` and `/me/access-keys` own their existing account resources.

The `/me` overview omits both a duplicate title bar and session actions, and
retains the flat four-item bottom destination row. Every child has a back action
and centered title, hides the bottom destination row, and falls back to its
fixed parent route. A
validated same-origin `returnTo` takes precedence when Library, Reader, or
another product context launched that child. Unsafe or external return targets
are ignored.

The responsive Settings launcher writes `?settings=` on desktop and the
corresponding `/me` path on phones. An old phone `?settings=` URL is replaced
with the new route while preserving other workspace state and the allowlisted
Zotero callback fields. Direct desktop visits to `/me` routes replace to the
equivalent existing Settings dialog, so account controls never acquire a
second desktop composition.

Desktop navigation uses 20 px semantic glyphs in fixed 24 px slots. The active
row and its icon strengthen together on one quiet hover surface; inactive icons
remain secondary. Settings selectors use the same light-line Select surface as
Reader and collection sorting; only dense desktop toolbars opt into its compact
height. Hover and open state never strengthen the resting border.

The user menu is the sole shell entry point on desktop. It uses the same
current-week billing query as Usage to show the live localized plan, Token
Credits used/limit, and the next UTC calendar day after the inclusive
`period_end` as the credit reset date. Loading and provider failure remain
compact, explicit states. Settings, Account, and Usage are separate actions:
Settings writes `?settings=general`, while Account and Usage write their named
sections. Appearance is not duplicated in the menu. The phone navigation hub
does not embed that dropdown: its identity row links to `/me`, and its bottom
utility area keeps only Search, New conversation, and the conditional Install
action. Routes mount one `SettingsDialog`; individual panels do not own another
modal shell. Desktop and mobile compositions share the same panel queries,
forms, mutations, feedback, and generated contracts while owning distinct
navigation shells. Every panel supports keyboard navigation, visible focus,
Light and Dark themes, English and Simplified Chinese, 320px containment, and
reduced-motion-safe feedback.

The account menu exposes localized Documentation and Repository rows with
semantic icons and explicit external-link affordances. The authentication
shell exposes the same public destinations before sign-in. Documentation opens
the public MCP guide; Repository opens the source for the running network
service without spending menu width on the license label.

## Panel responsibilities

- General is labeled Appearance. It owns application locale, curated Theme,
  the visual Light, Dark, and System choices, and the independent System,
  Reduced, and Full motion preference. Theme remains independent from
  Appearance and is stored only in the current browser. A Theme picker is
  omitted while only Default is registered and appears automatically once a
  second curated theme ships; Appearance previews always inherit the selected
  Theme.
- Account presents the authenticated Actor's shared identity as read-only,
  current-browser Sign out, and one external SanchezCloud Account action.
  The avatar is the private shared profile image managed by Account Center;
  missing, loading, expired, or unavailable images retain the same initials and
  geometry. The signed view refreshes before expiry and a missing image is
  checked again within fifteen minutes.
  Profile, email, and password editing are never exposed in Scholens.
  `https://myaccount.sanchezcloud.net` is the canonical destination and
  `NEXT_PUBLIC_ACCOUNT_CENTER_URL` may override it for an explicit environment.
- Usage owns plan and resource meters. Its selected period is local view state;
  Server returns exact period bounds, the plan's Token Credit limit, and the
  per-Project paper limit. Storage fields are explicitly KiB-valued
  `knowledge_base_size_kb` fields and Web converts them to KiB/MiB/GiB without
  changing their quantity. API date-only period bounds are always formatted in
  UTC so user time zones cannot move a calendar boundary to the previous day.
  Billing controls are omitted until real upgrade and portal workflows are
  connected; the interface does not present inert actions.
- Access Keys owns MCP key creation, rename, revoke, and one-time secret reveal.
  A secret is never recoverable after the creation acknowledgement is closed.
  Its panel header owns one action group on the right: the secondary
  `MCP setup guide` link to `/docs#mcp-setup` (new tab) next to the primary
  `Create access key` button, so configuration guidance never interrupts key
  management and creation no longer sits in a separate orphan row.
- Connections owns built-in and user-configured provider status. Scholight is
  built in; MinerU, AnySearch, Tavily, Exa, Firecrawl, and OpenAlex use the
  shared integration inventory and public `/me/integrations` contract. Zotero
  appears in that same inventory as a `reference_manager` connection, but its
  credential is established only through the dedicated read-only OAuth flow.
- Translation uses the same translation-preference feature as Reader. It does
  not duplicate server state or couple paper language to interface locale.

## MinerU connection contract

MinerU is user supplied. The connection form accepts a token from
`https://mineru.net/apiManage/token`, submits it once over the authenticated
Server API, and subsequently shows only status and a masked hint. Replacing a
token creates a new credential revision; disconnecting removes its availability
for future work. MinerU has no lightweight credential probe, so a newly saved
token remains enabled and is verified by the first real PDF or reflow request;
the connection state states that timing directly. UI copy must never imply that
Scholens supplies the token.

When PDF ingestion or AI reflow reports that MinerU is required, its action
opens Settings directly on Connections. The initiating surface retains one
pending intent and resumes it once after a newly saved connection is observed.
It does not loop, reuse a failed idempotency key for a different operation, or
hide the normal PDF/local fallback. Invalid credentials, rate limiting,
provider unavailability, insufficient content, and unsafe responses have
separate localized outcomes.

## OpenAlex connection contract

OpenAlex is user supplied and uses the official API-key page at
`https://openalex.org/settings/api`. Saving or re-enabling a key performs an
external `/rate-limit` probe before the short persistence command. The Web
shows connected, disabled, and invalid states but never receives the key or a
user-configurable endpoint. OpenAlex is categorized with search connections,
while remaining outside the dynamic MCP connector inventory.

A DOI submission that reports a missing or invalid OpenAlex credential keeps
the entered DOI, shows a dedicated explanation, and offers Connect OpenAlex.
That action closes Add Papers and opens Settings → Connections. Returning to
Add Papers preserves the DOI for an explicit resubmission; the Web does not
retry secretly after connection. Rate limiting and provider unavailability
remain separate retry-later messages.

## Zotero connection contract

Zotero connects a user's personal library with read-only files and notes
permission. Settings begins OAuth with a validated in-product return path and a
`manage` intent; the callback returns only to that path and exposes one stable
localized result code. The callback requires those personal-library read
capabilities but does not reject a key merely because Zotero attached additional
write or Group Library privileges. Scholens ignores those privileges and keeps
all provider calls personal and read-only. The OAuth-issued API key is never
shown, pasted into a form, or returned through a public status response.

Zotero uses the same compact provider row as every other connection. OAuth
feedback, invalid credentials, automatic-import preference, sync or cancel, and
disconnect remain inline rather than opening a provider-specific detail block.
Sync now creates a background operation for new annotations on papers already
imported into Scholens; it never imports another paper. Basic accounts remain in
this manual mode. Researcher accounts also see an automatic-import switch.
Automatic import is off by default, starts from the current Zotero
library-version checkpoint, and is disabled while Researcher access is absent.

Import and sync share one active Zotero operation per account. Settings restores
an active sync from the status kind and ID after refresh, retains its cancel
control, and disables a second start while either an import or sync is active.

Disconnecting prevents future browsing and sync but explicitly retains papers,
annotations, and operation history already stored by Scholens. Invalid
permission, revoked credentials, rate limiting, and provider unavailability
remain distinct recoverable states rather than raw Zotero diagnostics.

## State and component ownership

Settings panels compose product feature slices; they do not handwrite backend
DTOs. TanStack Query owns Server state, React Hook Form plus Zod owns editable
forms, and local state owns disclosure and confirmation interactions. Shared
integration queries live in `features/integrations`; shared content-language
preferences live in `features/translation-preferences`. Generic fields,
dialogs, feedback, and semantic Iconoir wrappers remain shared components.

## Acceptance states

Storybook covers Appearance, the conditional Theme picker, Account, Usage,
Access Keys, Connections, Translation, the mobile account overview and child
routes, 390px mobile, 320px containment, and Dark Chinese states. Account states
cover direct URL navigation, read-only identity, canonical and overridden
Account Center, current-session Sign out, mobile, and Dark. The shell account
menu covers real usage success, loading, failure/retry, keyboard open,
expanded/collapsed desktop, localized Dark mode, the Documentation and
Repository links, and the exact Settings/Account/Usage URL writes. The mobile
account center covers the fourth navigation destination, identity entry,
parent and validated-source returns, conditional Install, Account-owned Sign
out, long identity, billing success/loading/failure, and preference child
navigation.
Usage covers the per-Project paper limit, correct English/Chinese
KiB-derived storage display, and UTC-negative date-only formatting.
Connection stories include connected, not connected, invalid, replacement,
OpenAlex key-link, and OpenAlex invalid behavior.
`Features/Settings/Dialog/ZoteroConnected` is the executable Zotero management
state and covers its compact row, manual sync, automatic-import preference, and
disconnect confirmation. Adjacent Settings stories cover compact OAuth failure,
active-sync recovery, terminal failure, and invalid-credential recovery; the
Zotero feature stories own library slow, disconnected, invalid-permission,
rate-limit, narrow, localized, and Dark variants. Access Key stories include
empty, populated, create, edit, revoke, one-time secret states, the MCP guide
link, and its 320px header composition. The shared Dialog responsive-full story
verifies the mobile shell independently.

Feature changes must retain the Figma hierarchy, semantic tokens, generated API
types, localized copy parity, keyboard behavior, and narrow-content coverage.

## Motion acceptance

Settings keeps one dialog shell while the active panel performs a bounded
content swap. The navigation selection changes immediately and focus behavior
does not wait for the transition. Dialog presentation comes from the shared
responsive overlay recipe. General writes `scholens-motion` and updates the
root policy live; System follows the media query, Reduced removes spatial and
perpetual movement, and Full remains explicit even when the OS asks to reduce.
`Features/Settings/Dialog` → `General` and Motion Lab are the executable
preference evidence.
