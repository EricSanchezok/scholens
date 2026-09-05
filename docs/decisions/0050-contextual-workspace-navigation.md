# 0050 — Contextual Workspace navigation

Status: Accepted
Date: 2026-09-05
Owners: Web

## Problem

Scholens routes previously treated every visible back control as a fixed link.
Reader always returned to Library, Project detail always returned to the default
Projects list, and route remounts discarded collection position, global-search
state, sidebar disclosure, and unsent Conversation text. Browser Back, mobile
Back, and in-product return controls therefore described different histories.

The source route remains shareable URL state, while scroll anchors, focused
rows, search-dialog disclosure, and drafts are private session state. Putting
all of that state into URLs would expose noisy or sensitive interaction detail;
keeping every value page-local cannot survive a route boundary.

## Decision

The Web owns a focused `features/workspace-navigation` boundary. A normal
same-tab drill-in creates a versioned, actor-scoped navigation context in
`sessionStorage` and adds only its opaque `nav` token to the destination URL.
The context records the validated internal origin, semantic origin kind, stable
focus key, and registered restoration snapshots. It is bounded to the 64 most
recent contexts and falls back to process memory when browser storage is
unavailable.

Rendered link targets remain canonical. Modified clicks, new tabs, source-link
copy actions, and direct visits do not receive a generated context. Return uses
browser history only when the current entry carries the matching marker;
otherwise it replaces the route with the validated recorded origin. A missing
or invalid context uses the
destination's semantic fallback: Project Reader returns to that Project's
Papers view and personal Reader returns to Library.

Context-owned pushes, such as a Project-detail tab or Reader panel, increment a
depth marker while replacements retain it. Browser Back therefore traverses
those local layers one at a time, while a visible semantic return crosses the
recorded depth in one operation and lands on the original source entry.

Shareable tabs, queries, filters, sort, page, panel, Project, and Conversation
selection remain URL state. Query writers preserve an active `nav` token.
Collection scroll anchors, relative offsets, last focused row, unified-search
disclosure, and Workspace-rail collapse are session interaction state. Unsent
Conversation drafts are versioned and scoped by actor, surface, and existing or
new Conversation; they persist message, reasoning level, and research context.
They clear only after the Server accepts a turn, not when submission begins.

No backend API, database table, global state library, second router, route-wide
animation, or cross-tab draft synchronization is introduced.

## Alternatives considered

- Always call `history.back()`: rejected because direct links, reloads, and
  external referrers can leave Scholens or return to an unrelated surface.
- Put the complete origin and snapshots in query parameters: rejected because
  it makes shared URLs noisy, leaks interaction detail, and creates unbounded
  URLs.
- Keep fixed `/library` and `/projects` links: rejected because the label and
  destination cease to represent the user's task as soon as Reader or detail is
  entered from another surface.
- Add a global state library or retain every route DOM subtree: rejected because
  a focused Context plus URL, TanStack Query, React Hook Form, and bounded
  session storage cover the observed behavior.
- Store drafts on the Server: deferred because cross-device draft sync is a
  separate product and data-retention contract.

## Consequences

Reader, Library, Projects, Activity, unified search, and nested Reader links
share one return contract. Desktop and mobile use the same context while
retaining device-appropriate controls. Soft return can restore exact Query
state, virtual collection position, preview selection, and focus. Sidebar and
draft state no longer reset on ordinary route changes.

The internal token must be preserved by URL serializers but stripped from
remembered primary destinations and canonical shared links. New drill-in
surfaces must choose an origin kind and register only the smallest serializable
snapshot they need. Context schema changes require a version bump and bounded
fallback behavior.

## Validation

Vitest covers actor isolation, URL token behavior, registry bounds, destination
memory, and draft restoration. Playwright covers Library → Reader → exact
Library return and Projects → detail → exact Projects return, including source
focus. The complete Web gate remains the release check for browser history,
mobile composition, accessibility, localization, and production builds.
