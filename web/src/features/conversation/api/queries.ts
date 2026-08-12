import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import { conversationKeys, type ConversationListFilters } from "./keys";

export const conversationQueries = {
  list: (filters: ConversationListFilters = {}) =>
    queryOptions({
      queryKey: conversationKeys.list(filters),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/conversations", {
          params: {
            query: {
              archived: false,
              limit: 50,
              scope_type: filters.scopeType,
              scope_id: filters.scopeId,
            },
          },
          signal,
        });
        if (!data) throw new Error("Conversation list response was empty");
        return data;
      },
    }),
  detail: (conversationId: string) =>
    queryOptions({
      queryKey: conversationKeys.detail(conversationId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/conversations/{conversation_id}",
          { params: { path: { conversation_id: conversationId } }, signal },
        );
        if (!data) throw new Error("Conversation response was empty");
        return data;
      },
    }),
  turns: (conversationId: string) =>
    queryOptions({
      queryKey: conversationKeys.turns(conversationId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/conversations/{conversation_id}/turns",
          {
            params: {
              path: { conversation_id: conversationId },
              query: { limit: 100 },
            },
            signal,
          },
        );
        if (!data) throw new Error("Conversation turns response was empty");
        return data;
      },
    }),
};
