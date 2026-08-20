import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

type PaperCollection =
  | components["schemas"]["LibraryPaperCollection"]
  | components["schemas"]["PersonalLibraryPaperCollection"]
  | components["schemas"]["SelectedPaperCollection"];

export const paperSearchKeys = {
  all: ["paper-search"] as const,
  results: (query: string, collection: PaperCollection) =>
    [...paperSearchKeys.all, "results", query, collection] as const,
};

export const paperSearchQueries = {
  results: (query: string, collection: PaperCollection) =>
    queryOptions({
      enabled: query.trim().length >= 2,
      queryKey: paperSearchKeys.results(query, collection),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.POST("/api/v1/search/papers", {
          body: {
            collection,
            limit: 50,
            query: query.trim(),
            sort: "relevance",
          },
          signal,
        });
        if (!data) throw new Error("Paper search response was empty");
        return data;
      },
    }),
  infiniteResults: (query: string, collection: PaperCollection) =>
    infiniteQueryOptions({
      enabled: query.trim().length >= 2,
      initialPageParam: undefined as string | undefined,
      queryKey: [...paperSearchKeys.results(query, collection), "infinite"],
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.POST("/api/v1/search/papers", {
          body: {
            collection,
            cursor: pageParam,
            limit: 50,
            query: query.trim(),
            sort: "relevance",
          },
          signal,
        });
        if (!data) throw new Error("Paper search response was empty");
        return data;
      },
      getNextPageParam: (page) => page.next_cursor ?? undefined,
    }),
};

export type PaperSearchResult = components["schemas"]["PaperSearchResult"];
