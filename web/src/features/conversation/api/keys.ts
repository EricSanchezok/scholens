export type ConversationListFilters = {
  scopeType?: "global" | "project" | "paper";
  scopeId?: string;
  contextDocumentId?: string;
};

export const conversationKeys = {
  all: ["conversations"] as const,
  contextCatalog: () => [...conversationKeys.all, "context-catalog"] as const,
  contextPapers: (query: string) =>
    [...conversationKeys.contextCatalog(), "papers", query] as const,
  contextProjects: (query: string) =>
    [...conversationKeys.contextCatalog(), "projects", query] as const,
  lists: () => [...conversationKeys.all, "list"] as const,
  list: (filters: ConversationListFilters = {}) =>
    [...conversationKeys.lists(), filters] as const,
  details: () => [...conversationKeys.all, "detail"] as const,
  detail: (conversationId: string) =>
    [...conversationKeys.details(), conversationId] as const,
  turns: (conversationId: string) =>
    [...conversationKeys.detail(conversationId), "turns"] as const,
};
