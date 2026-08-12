export type ConversationListFilters = {
  scopeType?: "global" | "project" | "paper";
  scopeId?: string;
};

export const conversationKeys = {
  all: ["conversations"] as const,
  lists: () => [...conversationKeys.all, "list"] as const,
  list: (filters: ConversationListFilters = {}) =>
    [...conversationKeys.lists(), filters] as const,
  details: () => [...conversationKeys.all, "detail"] as const,
  detail: (conversationId: string) =>
    [...conversationKeys.details(), conversationId] as const,
  turns: (conversationId: string) =>
    [...conversationKeys.detail(conversationId), "turns"] as const,
};
