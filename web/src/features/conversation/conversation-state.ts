import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import type { ConversationStreamEvent } from "./api/conversations";

export type ConversationActivity =
  components["schemas"]["ConversationActivity"];
export type ConversationProgressEntry =
  components["schemas"]["ConversationProgressEntry"];
export type ConversationTrace = components["schemas"]["ConversationTrace"];
export type ConversationTraceEntry =
  ConversationProgressEntry | ConversationActivity;
export type ConversationAssistantItem =
  components["schemas"]["ConversationAssistantItem"];
export type ConversationTurn =
  components["schemas"]["ConversationTurnResponse"];
export type ProvisionalAssistantItem = Omit<
  ConversationAssistantItem,
  "phase"
> & { phase: "provisional" };
export type ConversationFailure = {
  code?: string;
  kind?: string;
  retryable: boolean;
  correlationId?: string;
  diagnosticId?: string;
};

export type LiveTurn = {
  turnId: string;
  responseId: string;
  variantIndex: number | null;
  generationKind: "initial" | "retry" | "branch";
  depth: number;
  userMessage: string;
  content: string;
  entries: ConversationTraceEntry[];
  provisionalItems: ProvisionalAssistantItem[];
  completedItemIds: string[];
  trace: ConversationTrace | null;
  references: Record<string, unknown> | null;
  suggestions: string[] | null;
  readyTurn: ConversationTurn | null;
  failure: ConversationFailure | null;
  durationMs: number | null;
  startedAtMs: number;
  connectionState: "connected" | "reconnecting" | "stop_failed";
  state: "streaming" | "ready" | "complete" | "cancelled" | "error";
};

export function createLiveTurn(
  turnId: string,
  responseId: string,
  userMessage: string,
  generationKind: "initial" | "retry" | "branch" = "initial",
  depth = 1,
  startedAtMs = Date.now(),
): LiveTurn {
  return {
    turnId,
    responseId,
    variantIndex: null,
    generationKind,
    depth,
    userMessage,
    content: "",
    entries: [],
    provisionalItems: [],
    completedItemIds: [],
    trace: null,
    references: null,
    suggestions: null,
    readyTurn: null,
    failure: null,
    durationMs: null,
    startedAtMs,
    connectionState: "connected",
    state: "streaming",
  };
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

export function conversationFailureFromValue(
  value: unknown,
): ConversationFailure {
  const payload = record(value);
  return {
    code: stringValue(payload?.code),
    kind: stringValue(payload?.kind),
    retryable: payload?.retryable === true,
    correlationId: stringValue(payload?.correlation_id),
    diagnosticId: stringValue(payload?.diagnostic_id),
  };
}

export function conversationFailureFromError(
  error: unknown,
): ConversationFailure {
  if (!(error instanceof ApiError)) return { retryable: false };
  const payload = record(error.details);
  return {
    ...conversationFailureFromValue(payload),
    code: error.code ?? stringValue(payload?.code),
    correlationId: error.correlationId ?? stringValue(payload?.correlation_id),
  };
}

function updateEntry(
  entries: ConversationTraceEntry[],
  entry: ConversationTraceEntry,
) {
  const existing = entries.find((item) => item.id === entry.id);
  if (
    existing?.kind === "activity" &&
    entry.kind === "activity" &&
    existing.state !== "running" &&
    entry.state === "running"
  ) {
    return entries;
  }
  return [...entries.filter((item) => item.id !== entry.id), entry].sort(
    (left, right) => left.sequence - right.sequence,
  );
}

function completeAssistantItem(
  current: LiveTurn,
  item: ConversationAssistantItem,
) {
  if (current.completedItemIds.includes(item.id)) return current;
  const completedItemIds = [...current.completedItemIds, item.id];
  const provisionalItems = current.provisionalItems.filter(
    (candidate) => candidate.id !== item.id,
  );
  if (item.phase === "progress") {
    return {
      ...current,
      completedItemIds,
      provisionalItems,
      entries: updateEntry(current.entries, {
        kind: "progress",
        id: item.id,
        sequence: item.sequence,
        content: item.content,
      }),
    };
  }
  return {
    ...current,
    completedItemIds,
    provisionalItems,
    content: item.content,
  };
}

export function reduceLiveTurn(
  current: LiveTurn | null,
  event: ConversationStreamEvent,
): LiveTurn | null {
  if (!current) return current;
  if (event.type === "response_ready") {
    if (event.turn.id !== current.turnId) return current;
    const response = event.turn.responses.find(
      (candidate) => candidate.id === current.responseId,
    );
    if (!response) return current;
    return {
      ...current,
      variantIndex: response.variant_index,
      content: response.content ?? current.content,
      entries: response.trace?.entries ?? current.entries,
      trace: response.trace,
      references: response.references as Record<string, unknown> | null,
      suggestions: event.turn.suggestions,
      readyTurn: event.turn,
      durationMs: response.duration_ms ?? current.durationMs,
      provisionalItems: [],
      state: "ready",
    };
  }
  if (event.response_id !== current.responseId) return current;
  if (event.type === "suggestions") {
    if (
      event.turn_id !== current.turnId ||
      (current.state !== "ready" && current.state !== "complete")
    ) {
      return current;
    }
    return {
      ...current,
      suggestions: event.suggestions,
      readyTurn: current.readyTurn
        ? { ...current.readyTurn, suggestions: event.suggestions }
        : null,
    };
  }
  if (event.type === "complete") {
    if (event.turn_id !== current.turnId || current.state !== "ready") {
      return current;
    }
    return { ...current, state: "complete" };
  }
  if (event.type === "cancelled") {
    if (event.turn_id !== current.turnId) return current;
    return {
      ...current,
      durationMs: Math.max(0, Date.now() - current.startedAtMs),
      state: "cancelled",
    };
  }
  if (event.type === "error") {
    if (current.state === "ready" || current.state === "complete") {
      return current;
    }
    return {
      ...current,
      failure: conversationFailureFromValue(event.error),
      durationMs: Math.max(0, Date.now() - current.startedAtMs),
      state: "error",
    };
  }
  if (event.type === "start") {
    return current.state === "streaming"
      ? { ...current, variantIndex: event.variant_index }
      : current;
  }
  if (current.state !== "streaming") return current;
  switch (event.type) {
    case "activity":
      return {
        ...current,
        entries: updateEntry(current.entries, event.activity),
      };
    case "assistant_item_start":
      if (
        current.completedItemIds.includes(event.item_id) ||
        current.provisionalItems.some((item) => item.id === event.item_id)
      ) {
        return current;
      }
      return {
        ...current,
        provisionalItems: [
          ...current.provisionalItems,
          {
            id: event.item_id,
            sequence: event.sequence,
            phase: "provisional" as const,
            content: "",
          },
        ].sort((left, right) => left.sequence - right.sequence),
      };
    case "assistant_item_delta":
      if (current.completedItemIds.includes(event.item_id)) return current;
      return {
        ...current,
        provisionalItems: current.provisionalItems.map((item) =>
          item.id === event.item_id
            ? { ...item, content: item.content + event.delta }
            : item,
        ),
      };
    case "assistant_item_complete":
      return completeAssistantItem(current, event.item);
    case "references":
      return {
        ...current,
        references: event.references as Record<string, unknown>,
      };
  }
}

export function reduceLiveTurnEvents(
  current: LiveTurn | null,
  events: ConversationStreamEvent[],
) {
  return events.reduce<LiveTurn | null>(reduceLiveTurn, current);
}
