# 0014 — Anchored annotation threads and Project audiences

Status: Accepted
Date: 2026-08-13
Owners: Scholens

## Problem

Reader currently presents Highlight and Add annotation as separate actions,
while the Server stores both as one highlight root with optional comments. Its
document scope and mutable `is_shared` flag conflate the marked Document with
the people allowed to see it. When one Document belongs to several Projects,
that model cannot express a discussion belonging to exactly one Project and it
allows a creator to delete other members' replies.

Scholens is pre-release and local product data is disposable. Preserving the
old contract would retain ambiguous ownership precisely when Reader is becoming
a Project collaboration surface.

## Decision

- `AnnotationThread` is the canonical aggregate and `annotation_thread` is the
  Research-item kind. It owns an immutable Document anchor, one color, an
  immutable audience, status, and a chronological list of comments.
- A highlight creates a thread with no comment. Commenting on a selection
  atomically creates the same thread and its first comment. Comments have no
  color, audience, or nested children.
- Research-item audience is independent of annotation target. Personal
  annotations are creator-only; Project annotations name exactly one Project
  and require the target Document to belong to it. Document-global annotation
  sharing is not supported.
- Project members may read and reply to open Project threads. Authors manage
  their own comments. Thread authors recolor their thread; thread authors,
  Project owners, and collaborators with `edit_project` may resolve or reopen
  it. A thread containing another author's contribution cannot be hard-deleted.
- Audience never changes after creation. Losing Project access immediately
  removes access to its threads. Removing a Project paper requires explicit
  confirmation when it will delete Project annotation threads.
- Project Reader combines the user's personal annotations with the current
  Project's threads. Highlight defaults to personal audience and Comment to the
  current Project, with an explicit pre-submit choice. Resolved threads are
  hidden from the PDF by default and remain available through a resolved filter.
- Reader collaboration uses focused ten-second polling and focus/local-action
  invalidation. Real-time transport, mentions, notifications, unread state,
  reactions, public annotations, and nested replies are separate capabilities.
- Project-context Reader conversations remain private user history. They are
  Project-scoped and carry the current paper as selected document context.

## Alternatives considered

- Separate Highlight and Comment resources were rejected because they duplicate
  anchors, colors, permissions, selection geometry, and panel navigation.
- A document-wide shared flag was rejected because it leaks one Project's
  discussion into another Project that happens to contain the same Document.
- Recursive replies were rejected because anchored document collaboration is
  clearer as one resolvable chronological thread.
- Confirmed cascade deletion was rejected once another author has replied;
  resolving preserves the conversation without granting silent ownership over
  other people's contributions.
- WebSocket delivery was deferred because bounded polling supplies the first
  collaboration slice without introducing another cross-feature event system.

## Consequences

The pre-release Research schema, public API, generated Web types, Agent/MCP
tools, Library projection, Zotero import, research search, and Reader turn
contexts replace highlight terminology together. The Reader URL gains Project
context and annotation queries become audience-aware. Project paper removal
must account for thread deletion, and Project conversation cursors bind the
selected context Document.

There is deliberately no compatibility route, field, enum value, decoder, or
data backfill. The local `scholens` schema is reset and rebuilt; the independent
`auth` schema is never dropped.

## Validation

Server tests prove audience/target consistency, member loss, contribution
protection, resolution permissions, Project-paper deletion counts, Zotero and
Library behavior, typed turn context, and Project conversation filtering. Web
stories and Reader E2E cover personal and Project defaults, filters, combined
overlays, resolution, polling, context loss, and Project-scoped private Ask.
