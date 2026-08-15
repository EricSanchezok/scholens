import type { components } from "@/lib/api/generated/schema";

type ConversationTurn = components["schemas"]["ConversationTurnResponse"];
type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];
export type ConversationListResponse =
  components["schemas"]["ConversationListResponse"];
export type ConversationTurnsResponse =
  components["schemas"]["ConversationTurnsResponse"];

export function updateConversationSummary(
  current: ConversationListResponse | undefined,
  conversationId: string,
  patch: Partial<ConversationSummary>,
): ConversationListResponse | undefined {
  if (!current) return current;
  return {
    ...current,
    items: current.items.map((conversation) =>
      conversation.id === conversationId
        ? { ...conversation, ...patch }
        : conversation,
    ),
  };
}

export function removeConversationSummary(
  current: ConversationListResponse | undefined,
  conversationId: string,
): ConversationListResponse | undefined {
  if (!current) return current;
  return {
    ...current,
    items: current.items.filter(
      (conversation) => conversation.id !== conversationId,
    ),
  };
}

export function upsertConversationTurn(
  current: ConversationTurnsResponse | undefined,
  turn: ConversationTurn,
): ConversationTurnsResponse {
  const items = [...(current?.items ?? [])];
  const index = items.findIndex((candidate) => candidate.id === turn.id);
  if (index >= 0) items[index] = turn;
  else {
    items.splice(
      0,
      items.length,
      ...items.filter((candidate) => candidate.depth < turn.depth),
      turn,
    );
  }
  items.sort((left, right) => left.depth - right.depth);
  return {
    items,
    path_revision: (current?.path_revision ?? 0) + (index >= 0 ? 0 : 1),
    next_cursor: current?.next_cursor ?? null,
  };
}

export function updateLatestTurnSuggestions(
  current: ConversationTurnsResponse | undefined,
  turnId: string,
  suggestions: string[],
): ConversationTurnsResponse | undefined {
  if (!current || current.items.at(-1)?.id !== turnId) return current;
  return {
    ...current,
    items: current.items.map((turn) =>
      turn.id === turnId ? { ...turn, suggestions } : turn,
    ),
  };
}
