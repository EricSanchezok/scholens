"use client";

import {
  LibraryIcon,
  WorkspaceActionIcon,
  InsightIcon,
  LinkIcon,
  ExpandIcon,
  DocumentIcon,
  SearchIcon,
  WarningIcon,
} from "@/design-system/icons/semantic-icons";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type {
  ConversationActivity,
  ConversationFailure,
  ProvisionalAssistantItem,
  ConversationPhase,
  ConversationTraceEntry,
  LiveTurn,
} from "../conversation-state";
import { isActiveConversationPhase } from "../conversation-state";
import { MessageContent } from "./message-content";

type ActivityBatch = {
  kind: "batch";
  id: string;
  sequence: number;
  state: ConversationActivity["state"];
  activities: ConversationActivity[];
};

export type WorklogRow =
  Extract<ConversationTraceEntry, { kind: "progress" }> | ActivityBatch;

export function groupWorklogEntries(
  entries: ConversationTraceEntry[],
): WorklogRow[] {
  const rows: WorklogRow[] = [];
  for (const entry of [...entries].sort(
    (left, right) => left.sequence - right.sequence,
  )) {
    if (entry.kind === "progress") {
      rows.push(entry);
      continue;
    }
    // Keep one row per real invocation.  Grouping consecutive calls made a
    // long research run look idle and hid which operation was still running.
    rows.push({
      kind: "batch",
      id: `activity:${entry.id}`,
      sequence: entry.sequence,
      state: entry.state,
      activities: [entry],
    });
  }
  return rows;
}

function activities(entries: ConversationTraceEntry[]) {
  return entries.filter(
    (entry): entry is ConversationActivity => entry.kind === "activity",
  );
}

function worklogSummary(
  entries: ConversationTraceEntry[],
  phase: ConversationPhase,
  sources: number,
  failure: ConversationFailure | null,
  connectionState: LiveTurn["connectionState"],
  stopFailure: boolean,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  const operations = activities(entries);
  if (phase === "cancelled") return t("activity.stopped");
  if (phase === "error") {
    if (failure?.code === "llm_stream_timeout") return t("failure.timeout");
    if (failure?.code === "llm_provider_response_invalid") {
      return t("failure.invalidResponse");
    }
    if (failure?.code === "llm_content_filtered") {
      return t("failure.contentFiltered");
    }
    if (failure?.code === "agent_orchestration_limit_exceeded") {
      return t("failure.operationLimit");
    }
    if (failure?.code === "llm_provider_authentication_failed") {
      return t("failure.configuration");
    }
    if (failure?.code?.endsWith("_unavailable")) {
      return t("failure.unavailable");
    }
    if (failure?.kind === "rate_limited") return t("failure.rateLimited");
    return t("activity.failed");
  }
  const running = operations.findLast(
    (activity) => activity.state === "running",
  );
  if (isActiveConversationPhase(phase)) {
    if (stopFailure) return t("failure.stopFailed");
    if (connectionState === "offline") return t("activity.reconnecting");
    if (connectionState === "reconnecting") return t("activity.reconnecting");
    if (running?.category === "search") return t("activity.searching");
    if (running?.category === "read") return t("activity.reading");
    if (running?.category === "workspace_action") {
      return t("activity.updatingWorkspace");
    }
    if (running?.category === "connector") {
      return t("activity.usingConnector", {
        connector: running.connector_name || t("activity.connectorFallback"),
      });
    }
    return t("activity.thinking");
  }
  const failed = operations.some((activity) => activity.state === "failed");
  return t(failed ? "activity.partialSummary" : "activity.completeSummary", {
    count: operations.length,
    sources,
  });
}

export function formatWorklogDuration(
  durationMs: number,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0
    ? t("duration.minutesSeconds", { minutes, seconds })
    : t("duration.seconds", { seconds });
}

function batchLabel(
  batch: ActivityBatch,
  t: ReturnType<typeof useTranslations<"Home.conversation">>,
) {
  const counts = new Map<ConversationActivity["category"], number>();
  for (const activity of batch.activities) {
    counts.set(activity.category, (counts.get(activity.category) ?? 0) + 1);
  }
  const activity = [...counts.entries()]
    .map(([category, count]) =>
      t(`activity.batch.${category}`, {
        count,
        connector:
          batch.activities.find((item) => item.category === "connector")
            ?.connector_name || t("activity.connectorFallback"),
      }),
    )
    .join(" · ");
  const state = {
    running: t("activity.state.running"),
    succeeded: t("activity.state.succeeded"),
    failed: t("activity.state.failed"),
  }[batch.state];
  return t("activity.batchState", { activity, state });
}

function ActivityBatchRow({ batch }: { batch: ActivityBatch }) {
  const t = useTranslations("Home.conversation");
  const failed = batch.activities.some(
    (activity) => activity.state === "failed",
  );
  const subjects = [
    ...new Set(
      batch.activities
        .map((activity) => activity.subject?.trim())
        .filter((subject): subject is string => Boolean(subject)),
    ),
  ];
  const visibleSubjects = subjects.slice(0, 2);
  const remaining = subjects.length - visibleSubjects.length;
  const categories = new Set(
    batch.activities.map((activity) => activity.category),
  );
  const category = categories.size === 1 ? [...categories][0] : undefined;
  const glyph = failed
    ? WarningIcon
    : category === "search"
      ? SearchIcon
      : category === "read"
        ? LibraryIcon
        : category === "workspace_action"
          ? WorkspaceActionIcon
          : category === "connector"
            ? LinkIcon
            : DocumentIcon;

  return (
    <li className="relative flex min-w-0 gap-2.5 py-1 lg:static">
      <span className="border-line bg-canvas absolute top-0.5 -left-[2.0625rem] grid size-6 shrink-0 place-items-center rounded-full border lg:static lg:mt-0.5 lg:size-auto lg:border-0 lg:bg-transparent">
        <Icon glyph={glyph} size={16} tone="secondary" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-foreground block text-sm leading-5 font-medium lg:inline lg:text-xs">
          {batchLabel(batch, t)}
        </span>
        {visibleSubjects.length > 0 && (
          <span className="text-muted mt-0.5 block text-sm leading-5 [overflow-wrap:anywhere] lg:ms-2 lg:mt-0 lg:inline lg:text-xs">
            {visibleSubjects.join(" · ")}
            {remaining > 0
              ? ` · ${t("activity.more", { count: remaining })}`
              : ""}
          </span>
        )}
      </span>
    </li>
  );
}

export function ConversationWorklog({
  entries,
  sourceTotal,
  phase,
  failure,
  provisionalItems,
  historical = false,
  onOpenChange,
  durationMs,
  startedAtMs,
  connectionState = "connected",
  stopFailure = false,
}: {
  entries: ConversationTraceEntry[];
  sourceTotal: number;
  phase: ConversationPhase;
  failure: ConversationFailure | null;
  provisionalItems: ProvisionalAssistantItem[];
  historical?: boolean;
  onOpenChange?: (open: boolean) => void;
  durationMs?: number | null;
  startedAtMs?: number;
  connectionState?: LiveTurn["connectionState"];
  stopFailure?: boolean;
}) {
  const t = useTranslations("Home.conversation");
  const [manualOpen, setManualOpen] = React.useState<boolean | null>(null);
  const [liveNow, setLiveNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!isActiveConversationPhase(phase) || startedAtMs === undefined) return;
    const interval = window.setInterval(() => setLiveNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [phase, startedAtMs]);
  const rows = React.useMemo(
    () =>
      groupWorklogEntries([
        ...entries,
        ...provisionalItems
          .filter((item) => item.content)
          .map((item) => ({
            kind: "progress" as const,
            id: item.id,
            sequence: item.sequence,
            content: item.content,
          })),
      ]),
    [entries, provisionalItems],
  );
  const provisionalItemIds = React.useMemo(
    () => new Set(provisionalItems.map((item) => item.id)),
    [provisionalItems],
  );
  const hasDetails = rows.length > 0;
  const open =
    manualOpen ??
    (!historical && isActiveConversationPhase(phase) && hasDetails);
  const visible =
    hasDetails ||
    phase === "cancelled" ||
    phase === "error" ||
    isActiveConversationPhase(phase) ||
    durationMs != null;
  const summary = worklogSummary(
    entries,
    phase,
    sourceTotal,
    failure,
    connectionState,
    stopFailure,
    t,
  );
  const effectiveDuration =
    durationMs ??
    (isActiveConversationPhase(phase) && startedAtMs !== undefined
      ? Math.max(0, liveNow - startedAtMs)
      : null);
  const durationLabel =
    effectiveDuration === null
      ? null
      : formatWorklogDuration(effectiveDuration, t);
  const finalDurationAnnouncement =
    !isActiveConversationPhase(phase) && durationLabel
      ? t("duration.completed", { duration: durationLabel })
      : null;

  if (!visible) return null;

  function toggle() {
    if (!hasDetails) return;
    const next = !open;
    setManualOpen(next);
    onOpenChange?.(next);
  }

  return (
    <section
      className="text-secondary min-w-0 text-[0.9375rem] leading-6 lg:text-sm lg:leading-normal"
      data-state={phase}
    >
      {!historical && phase !== "ready" ? (
        <span
          aria-atomic="true"
          aria-live="polite"
          className="sr-only"
          role="status"
        >
          {summary}
          {finalDurationAnnouncement ? ` ${finalDurationAnnouncement}` : ""}
        </span>
      ) : null}
      {hasDetails ? (
        <button
          aria-expanded={open}
          className={cn(
            "motion-control hover:text-foreground focus-visible:text-foreground inline-flex min-h-11 w-fit max-w-full items-center gap-1.5 rounded-[var(--radius-sm)] text-left lg:min-h-8",
            focusSurfaceVariants({ intent: "inline" }),
          )}
          onClick={toggle}
          type="button"
        >
          <span className="settled-content-enter min-w-0" key={summary}>
            {summary}
            {durationLabel ? (
              <span aria-hidden={!historical}> · {durationLabel}</span>
            ) : null}
          </span>
          <Icon
            className={cn("motion-icon shrink-0", open && "rotate-180")}
            glyph={ExpandIcon}
            size={16}
            tone="secondary"
          />
        </button>
      ) : (
        <p className="flex min-h-11 items-center lg:min-h-8">
          <span className="settled-content-enter" key={summary}>
            {summary}
            {durationLabel ? (
              <span aria-hidden={!historical}> · {durationLabel}</span>
            ) : null}
          </span>
        </p>
      )}
      {open && hasDetails && (
        <ol className="settled-content-enter border-line relative mt-2 ml-3 grid min-w-0 gap-2 border-s pb-1 pl-5 lg:mt-1 lg:ml-0 lg:gap-1 lg:border-s-0 lg:pl-0">
          {rows.map((row) =>
            row.kind === "progress" ? (
              <li
                className="text-foreground relative min-w-0 py-1 [overflow-wrap:anywhere] lg:static"
                key={row.id}
              >
                <span className="border-line bg-canvas absolute top-0.5 -left-[2.0625rem] grid size-6 place-items-center rounded-full border lg:hidden">
                  <Icon glyph={InsightIcon} size={16} tone="secondary" />
                </span>
                <MessageContent
                  content={row.content}
                  streaming={
                    isActiveConversationPhase(phase) &&
                    provisionalItemIds.has(row.id)
                  }
                />
              </li>
            ) : (
              <ActivityBatchRow batch={row} key={row.id} />
            ),
          )}
        </ol>
      )}
      {phase === "error" && failure?.diagnosticId && (
        <p className="text-muted mt-1 text-xs">
          {t("failure.diagnostic", { id: failure.diagnosticId })}
        </p>
      )}
    </section>
  );
}
