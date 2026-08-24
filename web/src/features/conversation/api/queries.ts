import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import { isSearchQuery, normalizeSearchQuery } from "@/lib/search/query";
import { conversationKeys, type ConversationListFilters } from "./keys";

export const conversationQueries = {
  contextPapers: (query: string) =>
    queryOptions({
      queryKey: conversationKeys.contextPapers(query),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/papers", {
          params: {
            query: {
              limit: 100,
              q: query || undefined,
              sort: "added_desc",
            },
          },
          signal,
        });
        if (!data) throw new Error("Context paper catalog was empty");
        return data;
      },
    }),
  contextProjects: (query: string) =>
    queryOptions({
      queryKey: conversationKeys.contextProjects(query),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/projects", {
          params: {
            query: {
              limit: 100,
              q: query || undefined,
              sort: "activity_desc",
            },
          },
          signal,
        });
        if (!data) throw new Error("Context project catalog was empty");
        return data;
      },
    }),
  list: (filters: ConversationListFilters = {}) =>
    queryOptions({
      queryKey: conversationKeys.list(filters),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/conversations", {
          params: {
            query: {
              archived: false,
              context_document_id: filters.contextDocumentId,
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
  infiniteList: (filters: ConversationListFilters = {}) =>
    infiniteQueryOptions({
      initialPageParam: undefined as string | undefined,
      queryKey: conversationKeys.infiniteList(filters),
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.GET("/api/v1/conversations", {
          params: {
            query: {
              archived: false,
              context_document_id: filters.contextDocumentId,
              cursor: pageParam,
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
      getNextPageParam: (page) => page.next_cursor ?? undefined,
    }),
  infiniteSearch: (query: string) => {
    const normalizedQuery = normalizeSearchQuery(query);
    return infiniteQueryOptions({
      enabled: isSearchQuery(normalizedQuery),
      initialPageParam: undefined as string | undefined,
      queryKey: conversationKeys.search(normalizedQuery),
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.POST("/api/v1/search/conversations", {
          body: {
            cursor: pageParam,
            limit: 30,
            query: normalizedQuery,
          },
          signal,
        });
        if (!data) throw new Error("Conversation search response was empty");
        return data;
      },
      getNextPageParam: (page) => page.next_cursor ?? undefined,
    });
  },
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
