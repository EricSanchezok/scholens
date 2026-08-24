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
export type ConversationResponseStatus =
  components["schemas"]["ConversationResponseVariantResponse"]["status"];
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

export type ConversationPhase =
  | "submitting"
  | "queued"
  | "working"
  | "answering"
  | "finalizing"
  | "ready"
  | "cancelled"
  | "error";

export type ConversationConnectionState =
  "connecting" | "connected" | "reconnecting" | "offline";

export function isActiveConversationPhase(phase: ConversationPhase) {
  return (
    phase === "submitting" ||
    phase === "queued" ||
    phase === "working" ||
    phase === "answering" ||
    phase === "finalizing"
  );
}

export type LiveTurn = {
  turnId: string;
  responseId: string;
  variantIndex: number | null;
  generationKind: "initial" | "retry" | "branch";
  depth: number;
  userMessage: string;
  content: string;
  entries: ConversationTraceEntry[];
  answerCandidate: ProvisionalAssistantItem | null;
  provisionalItems: ProvisionalAssistantItem[];
  completedItemIds: string[];
  trace: ConversationTrace | null;
  references: Record<string, unknown> | null;
  suggestions: string[] | null;
  readyTurn: ConversationTurn | null;
  failure: ConversationFailure | null;
  durationMs: number | null;
  startedAtMs: number;
  connectionState: ConversationConnectionState;
  phase: ConversationPhase;
  stopFailure: boolean;
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
    answerCandidate: null,
    provisionalItems: [],
    completedItemIds: [],
    trace: null,
    references: null,
    suggestions: null,
    readyTurn: null,
    failure: null,
    durationMs: null,
    startedAtMs,
    connectionState: "connecting",
    phase: "submitting",
    stopFailure: false,
  };
}

export function persistedResponseStatus(
  turns: ConversationTurn[] | undefined,
  turnId: string,
  responseId: string,
): ConversationResponseStatus | undefined {
  return turns
    ?.find((turn) => turn.id === turnId)
    ?.responses.find((response) => response.id === responseId)?.status;
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
  const answerCandidate =
    item.phase === "final" || current.answerCandidate?.id === item.id
      ? null
      : current.answerCandidate;
  const provisionalItems = current.provisionalItems.filter(
    (candidate) => candidate.id !== item.id,
  );
  if (item.phase === "progress") {
    return {
      ...current,
      completedItemIds,
      answerCandidate,
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
    answerCandidate,
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
      answerCandidate: null,
      provisionalItems: [],
      connectionState: "connected",
      phase: "ready",
    };
  }
  if (event.response_id !== current.responseId) return current;
  if (event.type === "suggestions") {
    if (event.turn_id !== current.turnId || current.phase !== "ready") {
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
    if (event.turn_id !== current.turnId || current.phase !== "ready") {
      return current;
    }
    return current;
  }
  if (event.type === "cancelled") {
    if (event.turn_id !== current.turnId) return current;
    return {
      ...current,
      answerCandidate: null,
      durationMs: Math.max(0, Date.now() - current.startedAtMs),
      phase: "cancelled",
    };
  }
  if (event.type === "error") {
    if (current.phase === "ready") {
      return current;
    }
    return {
      ...current,
      answerCandidate: null,
      failure: conversationFailureFromValue(event.error),
      durationMs: Math.max(0, Date.now() - current.startedAtMs),
      phase: "error",
    };
  }
  if (event.type === "start") {
    return current.phase === "submitting" || current.phase === "queued"
      ? {
          ...current,
          connectionState: "connected",
          phase: "queued",
          variantIndex: event.variant_index,
        }
      : current;
  }
  if (
    current.phase === "ready" ||
    current.phase === "cancelled" ||
    current.phase === "error"
  ) {
    return current;
  }
  switch (event.type) {
    case "activity":
      return {
        ...current,
        entries: updateEntry(current.entries, event.activity),
        phase: current.phase === "answering" ? "answering" : "working",
      };
    case "assistant_candidate_start":
      if (
        current.completedItemIds.includes(event.item_id) ||
        current.answerCandidate?.id === event.item_id
      ) {
        return current;
      }
      return {
        ...current,
        answerCandidate: {
          id: event.item_id,
          sequence: event.sequence,
          phase: "provisional" as const,
          content: "",
        },
        phase: current.phase === "answering" ? "answering" : "working",
      };
    case "assistant_item_start":
      if (current.completedItemIds.includes(event.item_id)) return current;
      if (current.answerCandidate?.id === event.item_id) return current;
      if (current.provisionalItems.some((item) => item.id === event.item_id)) {
        return {
          ...current,
          provisionalItems: current.provisionalItems.map((item) =>
            item.id === event.item_id ? { ...item, content: "" } : item,
          ),
        };
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
        phase: current.phase === "answering" ? "answering" : "working",
      };
    case "assistant_candidate_reset":
      if (current.completedItemIds.includes(event.item_id)) return current;
      if (current.answerCandidate?.id !== event.item_id) return current;
      return {
        ...current,
        answerCandidate: { ...current.answerCandidate, content: "" },
        phase: "working",
      };
    case "assistant_candidate_delta":
      if (
        current.completedItemIds.includes(event.item_id) ||
        current.answerCandidate?.id !== event.item_id
      ) {
        return current;
      }
      return {
        ...current,
        answerCandidate: {
          ...current.answerCandidate,
          content: current.answerCandidate.content + event.delta,
        },
        phase: "answering",
      };
    case "assistant_item_delta":
      if (current.completedItemIds.includes(event.item_id)) return current;
      if (current.answerCandidate?.id === event.item_id) return current;
      return {
        ...current,
        provisionalItems: current.provisionalItems.map((item) =>
          item.id === event.item_id
            ? { ...item, content: item.content + event.delta }
            : item,
        ),
        phase: "answering",
      };
    case "assistant_item_complete":
      return {
        ...completeAssistantItem(current, event.item),
        phase: event.item.phase === "final" ? "finalizing" : current.phase,
      };
    case "references":
      return {
        ...current,
        references: event.references as Record<string, unknown>,
        phase: "finalizing",
      };
  }
}

export function reduceLiveTurnEvents(
  current: LiveTurn | null,
  events: ConversationStreamEvent[],
) {
  return events.reduce<LiveTurn | null>(reduceLiveTurn, current);
}
