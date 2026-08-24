import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { isSearchQuery, normalizeSearchQuery } from "@/lib/search/query";

type PaperCollection =
  | components["schemas"]["LibraryPaperCollection"]
  | components["schemas"]["PersonalLibraryPaperCollection"]
  | components["schemas"]["SelectedPaperCollection"];
type PaperSearchFilters = components["schemas"]["PaperSearchFilters"];

export const paperSearchKeys = {
  all: ["paper-search"] as const,
  results: (query: string, collection: PaperCollection) =>
    [...paperSearchKeys.all, "results", query, collection] as const,
};

export const paperSearchQueries = {
  results: (
    query: string,
    collection: PaperCollection,
    filters: PaperSearchFilters = {},
  ) => {
    const normalizedQuery = normalizeSearchQuery(query);
    return queryOptions({
      enabled: isSearchQuery(normalizedQuery),
      queryKey: [
        ...paperSearchKeys.results(normalizedQuery, collection),
        filters,
      ],
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.POST("/api/v1/search/papers", {
          body: {
            collection,
            filters,
            limit: 50,
            query: normalizedQuery,
            sort: "relevance",
          },
          signal,
        });
        if (!data) throw new Error("Paper search response was empty");
        return data;
      },
    });
  },
  infiniteResults: (
    query: string,
    collection: PaperCollection,
    filters: PaperSearchFilters = {},
  ) => {
    const normalizedQuery = normalizeSearchQuery(query);
    return infiniteQueryOptions({
      enabled: isSearchQuery(normalizedQuery),
      initialPageParam: undefined as string | undefined,
      queryKey: [
        ...paperSearchKeys.results(normalizedQuery, collection),
        filters,
        "infinite",
      ],
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.POST("/api/v1/search/papers", {
          body: {
            collection,
            filters,
            cursor: pageParam,
            limit: 50,
            query: normalizedQuery,
            sort: "relevance",
          },
          signal,
        });
        if (!data) throw new Error("Paper search response was empty");
        return data;
      },
      getNextPageParam: (page) => page.next_cursor ?? undefined,
    });
  },
};

export type PaperSearchResult = components["schemas"]["PaperSearchResult"];
