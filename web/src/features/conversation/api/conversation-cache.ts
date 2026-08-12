import type { components } from "@/lib/api/generated/schema";

type ConversationTurn = components["schemas"]["ConversationTurnResponse"];
export type ConversationTurnsResponse =
  components["schemas"]["ConversationTurnsResponse"];

export function upsertConversationTurn(
  current: ConversationTurnsResponse | undefined,
  turn: ConversationTurn,
): ConversationTurnsResponse {
  const items = [...(current?.items ?? [])];
  const index = items.findIndex((candidate) => candidate.id === turn.id);
  if (index >= 0) items[index] = turn;
  else items.push(turn);
  items.sort((left, right) => left.sequence - right.sequence);
  return { items, next_cursor: current?.next_cursor ?? null };
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
