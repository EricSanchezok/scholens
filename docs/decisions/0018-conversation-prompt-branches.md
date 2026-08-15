# 0018 — Conversation prompts form durable selected branches

Status: Accepted
Date: 2026-08-15
Owners: Scholens
Supersedes: [ADR 0009](./0009-turn-response-variants.md)

## Problem

Users need to edit any visible prompt and continue from that historical point
without overwriting the original research record. The former flat turn sequence
could preserve retry variants for only the latest prompt, but it could not
represent alternate prompts, restore their complete suffixes after refresh, or
keep Agent history and paper context on the selected alternative.

## Decision

A Conversation owns a persistent tree of `ConversationTurn` rows and one active
root-to-leaf path.

- A turn stores `parent_turn_id`, one-based `depth` and `branch_index`, and the
  `selected_child_turn_id` used when its subtree is active. A Conversation stores
  `selected_root_turn_id` and a monotonic `path_revision`.
- Editing a prompt creates a sibling turn through
  `POST /conversations/{id}/turns/{turn_id}/branches`; it never mutates or
  deletes the source turn. Selecting a sibling through
  `PUT /conversations/{id}/selected-branch` restores that sibling's previously
  selected descendant suffix and returns the authoritative active path.
- Agent history contains only the selected ancestors of the generated turn.
  The Server permits one running response for the whole Conversation and
  permits retry and response-variant selection only on the active leaf.
- A turn stores its typed paper-context snapshot alongside typed Reader
  contexts, reasoning level, locale, and time zone. Creating or selecting a
  branch restores that snapshot only after current resource authorization.
- Branch preparation is read-only: it carries the source turn's immutable
  paper-context snapshot through quota, authorization, context resolution,
  rate-limit, and concurrency checks. The single acceptance transaction then
  restores the Conversation paper context, creates the sibling Turn and
  Response, changes the selected path, and increments `path_revision` together.
  A rejected preflight leaves all four unchanged; after that transaction
  commits, `start` is always the first SSE event and later failures become a
  persisted, safely retryable terminal attempt.
- Turn ID replay is accepted only when the normalized prompt, typed contexts,
  paper-context snapshot, reasoning level, locale, time zone, parent, and depth
  all match the active leaf. Any mismatch is one `conversation_turn_conflict`
  that rolls the acceptance transaction back. Re-selecting the current branch
  is a storage and Operation Journal no-op; an actual path or restored-context
  change emits exactly one branch-selection journal entry.
- Response variants remain children of one prompt. Starting a normal next turn
  prunes unselected response variants and suggestions from its parent, but
  prompt branches and their selected suffixes are retained.
- A response stores `duration_ms` for completed, failed, and cancelled
  generation. Duration is response metadata; ordered worklog entries remain the
  authority for inspectable progress.
- The latest terminal response attempt becomes the turn selection even when it
  failed or was cancelled. The active leaf serializes all terminal attempts so
  its generic safe failure state, duration, and retry position survive refresh;
  raw exception text remains private diagnostics.
- Active-path cursors carry `path_revision`; a branch change invalidates stale
  pagination instead of joining turns from different paths.

This is a reset-first pre-release schema change. `sequence` and the untyped turn
`scope` payload are removed from the initial migration, with no compatibility
DTO, dual read path, or backfill.

## Alternatives considered

- Mutate the historical prompt and regenerate in place. Rejected because it
  destroys provenance and makes sources, artifacts, and prior answers
  misleading.
- Keep branches only in browser state. Rejected because refresh, Reader entry,
  Agent history, and multi-device use would disagree.
- Copy the whole suffix for every edit. Rejected because it duplicates durable
  responses and citations; selected child pointers express the same product
  behavior without cloning.
- Preserve the flat sequence and add a version array to each turn. Rejected
  because descendants belong to a particular prompt version, so the aggregate
  would still need an implicit tree.

## Consequences

Prompt alternatives, their selected response variants, sources, and descendant
suffixes survive refresh. Branch selection is an aggregate command rather than
a local rendering preference, and pagination must detect path revisions. The
Server must serialize sibling navigation metadata and reauthorize restored
paper context. Storage can grow with intentional prompt branches, while retry
variants remain bounded when a normal continuation is created.

## Validation

Server contract tests cover tree selection, sibling metadata, read-only branch
preflight, atomic context/path acceptance, quota/rate/capacity rejection,
strict Turn ID replay, no-op branch selection, one-running-response enforcement,
lease release on conflict, stale cursor rejection, duration persistence, and
failed/cancelled finalization. Generated
OpenAPI types, Web reducer tests, Storybook states, and Playwright journeys cover
editing any active-path user message, pre-acceptance draft retention,
full-suffix switching, refresh, and keyboard/mobile behavior.
