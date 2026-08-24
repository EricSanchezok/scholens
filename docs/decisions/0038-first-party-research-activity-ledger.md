# 0038 — First-party research activity ledger

Status: Accepted
Date: 2026-08-24
Owners: Scholens

## Problem

Scholens can store papers, conversations, annotations, outputs, and Project
membership, but those durable objects do not explain the work between import
and output. A researcher cannot see how long they actively worked with a paper,
which pages they returned to, how their research rhythm changed, or how a
Project progressed over time. Project Overview consequently over-emphasizes
inventory and under-represents effort and process.

Browser dwell is also easy to overstate. A foreground tab, recent interaction,
and a visible page are useful evidence, but they do not prove attention,
comprehension, or research quality. Exact member timelines can expose working
patterns inside a shared Project, while a single productivity score or
leaderboard would turn an uncertain proxy into a target that can be gamed.

The product direction is grounded in four external reference points. Zotero's
Reader keeps annotations as document-local, page-addressable evidence rather
than a detached analytics stream; Readwise's Stats experience demonstrates the
motivational value of calendars and document-level review history. The W3C Page
Visibility contract and the browser Page Lifecycle model define the bounded
foreground/lifecycle signals available to Web. Research on reading analytics
also warns that fine-grained behavioral traces create a distinct reader-
privacy risk. These references inform the interaction and minimization choices
below; none is treated as a claim that dwell proves comprehension.

PostHog-style product analytics and OpenTelemetry serve different operators and
retention policies. Reusing either as the product record would put high-
cardinality personal research behavior in an observability system, weaken
authorization and deletion guarantees, and make user-facing history depend on
telemetry sampling or eviction.

## Decision

Scholens owns a first-party research-activity ledger in `scholens.*`. It keeps
three concepts separate:

- **reading evidence** records bounded Reader sessions, page and vertical-region
  dwell, visible time, and an active-time estimate;
- **derived insights** aggregate that evidence by paper, UTC hour, personal
  account, and optional Project attribution;
- **research facts** such as adding a paper, creating an annotation or output,
  commenting, and changing Project membership remain owned by their existing
  canonical aggregates. The Project activity feed is an authorized read
  projection over those rows, not a copied event table.

PostHog, OpenTelemetry traces, logs, metrics, the Operation Journal, and Jobs are
not a source of truth for this ledger. Operational telemetry may report only
low-cardinality health and failure facts; it must not contain session paths,
page histories, selected text, research content, or raw actor timelines.

### Measurement contract

The initial metric definition is `active-reading-v1`. The Web increments
visible dwell only while the Reader document is visible in a foreground,
focused browser. It increments the active estimate only while qualifying user
interaction is no more than 120 seconds old. Time is admitted in bounded
five-second slices and cumulative session updates flush at most every 30
seconds and at lifecycle boundaries. Server validates monotonic cumulative
visible and active durations and requires active duration not to exceed visible
duration.

A page becomes substantively visited after 15 seconds of active estimate.
Page-local position is reduced to 20 normalized vertical regions rather than
storing pointer, selection, or viewport coordinates. Every stored and returned
estimate carries its metric-definition version. Later calibration creates a
new definition; it does not silently reinterpret historical values.

The product calls these values estimates. It never presents active reading time
as gaze, attention, comprehension, productivity, or proof that a paper was
read. Reading duration does not affect permissions, plans, billing, academic
evaluation, or automated performance decisions. Reader heatmaps pair color
with numeric values and a legend, and distinguish unvisited, unavailable, and
not-yet-recorded states. Scholens does not create a cross-user productivity
score, member ranking, or reading-time leaderboard.

### Privacy, retention, and control

Reading recording and contribution to anonymous Project aggregates are
independent user preferences. Both default to enabled and are plainly
controllable in Settings. Disabling either preference stops the corresponding
future collection or contribution; it does not pretend that previously stored
history was deleted. Explicit Project operations and their canonical facts
continue to exist even when behavioral reading recording is off.

Personal sessions, page history, and insights are private to their owner.
Project members receive only a selected-period aggregate when at least three
distinct members contributed during that period. Team reading time is rounded
to five-minute units. The contract exposes no member selector, individual
timeline, exact session boundary, or member-level reading contribution.

Fine-grained session-page trajectories have a 90-day retention ceiling.
Coarse sessions and personal page/hour rollups remain until the user deletes
them or the account is deleted. Project-attributed rollups remain until the
contributor removes that attribution, the source activity is deleted, or the
Project is deleted. Deleting only a Project contribution preserves the user's
personal reading history. Account deletion cascades all personal sessions,
rollups, preferences, and Project contributions.

The user can export their activity as JSON or CSV and can delete one session
while its page detail remains, one paper's activity, one Project contribution,
or all reading activity. Once the 90-day purge has removed the deltas needed to
reverse one session safely, that narrow deletion returns a stable conflict and
the exact paper, Project-contribution, and all-history deletions remain
available. New insight responses disclose when recording began and whether the
requested history window is complete; Scholens performs no retroactive duration
backfill from legacy last-access timestamps or canonical Project facts.

### Layer ownership

| Layer | Owner | Contract |
| --- | --- | --- |
| Product UI | Web Reader, Home, Projects, and Me/Settings feature slices | Reader supplies bounded visibility and interaction evidence; Reader shows private paper insight, Home links a compact personal snapshot to `/me/activity`, Project Overview shows private-self plus thresholded team insight and canonical activity, and Settings owns recording/sharing controls. |
| Public interface | Server HTTP `/api/v1` | Preference reads/writes, session create/update, paper/Project/personal insight queries, Project activity, export, and scoped deletion are generated public contracts. Server authenticates, authorizes, validates cumulative evidence, applies anonymity, and returns completeness metadata. |
| Durable data | Server-owned PostgreSQL `scholens.*` | Preferences, sessions, 90-day session-page detail, and personal/Project page and UTC-hour rollups are the activity source of truth. Existing paper, annotation, output, and collaboration tables remain the Project-fact source of truth. |

## Alternatives considered

- **Use PostHog events as the ledger.** Rejected because sampling, analytics
  retention, operator access, and identity resolution do not provide the
  product authorization, export, or deletion contract.
- **Derive the product from OpenTelemetry traces or logs.** Rejected because
  observability data describes service execution, not user-owned research data,
  and must remain low-cardinality and independently disposable.
- **Keep all reading history in the browser.** Rejected because it cannot
  survive device changes, drive an authorized Project aggregate, or offer one
  account-level export and deletion boundary.
- **Measure every open-tab millisecond or retain raw heartbeats indefinitely.**
  Rejected because background and idle time inflate the result, while an
  unbounded interaction stream creates privacy and storage cost without a
  defensible insight.
- **Expose exact member contributions, rankings, or a composite productivity
  score.** Rejected because uncertain proxies become surveillance and gaming
  targets and because research outcomes cannot be reduced to elapsed time.
- **Copy every Project action into an activity-facts table.** Rejected because
  it introduces dual writes and allows the feed to drift from papers,
  annotations, outputs, comments, and collaboration records that already own
  those facts.

## Consequences

Research effort becomes visible across one paper, the personal research year,
and a shared Project without making observability infrastructure a product
database. The same evidence can support heatmaps, trends, coverage, and private
milestones while output and collaboration facts retain their original meaning.

The Web must handle visibility, focus, idle, lifecycle flush, offline retry,
and duplicate delivery consistently. Server needs additive public contracts,
forward-only schema changes, retention maintenance, rollup repair, export, and
deletion tests. A small Project may show an intentionally unavailable team
aggregate, and fine page-level session history becomes unavailable after 90
days even though coarse personal trends remain. Product copy and accessible
legends must continually resist interpreting an estimate as comprehension.

Default-on collection increases the obligation to make the controls discoverable
and the first-run explanation honest. A future change to the default, anonymity
threshold, retention ceiling, or allowed decision use requires an explicit
privacy review and an amendment or superseding decision.

## Validation

- Browser tests cover foreground/background, focus loss, 120-second idle,
  five-second admission, 30-second flush, reconnect, duplicate update, page
  navigation, and a closed recording preference.
- Server tests prove ownership, active-not-greater-than-visible validation,
  definition-version projection, 15-second substantive coverage, 20-region
  bounds, three-contributor suppression, five-minute team rounding, and the
  absence of member-level team fields.
- Retention and deletion tests prove the 90-day detail ceiling, personal versus
  Project-attribution separation, the purged-session conflict, exact broader
  deletion, export authorization, Project deletion, and account cascade.
- Contract and telemetry tests prove that activity endpoints are additive and
  that session/page payloads do not enter PostHog, traces, logs, metrics, the
  Operation Journal, or job envelopes.

## References

- [Zotero PDF Reader and Note Editor](https://www.zotero.org/support/pdf_reader)
- [Readwise Stats changelog](https://readwise.io/changelog/stats)
- [W3C Page Visibility Level 2](https://www.w3.org/TR/page-visibility-2/)
- [Chrome Page Lifecycle API](https://developer.chrome.com/docs/web-platform/page-lifecycle-api)
- [The rise of reading analytics and the emerging calculus of reader privacy](https://firstmonday.org/ojs/index.php/fm/article/view/7414)
