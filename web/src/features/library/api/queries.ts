import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type {
  LibrarySearchState,
  OutputKind,
  OutputSort,
  PaperSort,
} from "../library-search";
import { libraryKeys } from "./keys";

export const libraryQueries = {
  conversations: () =>
    queryOptions({
      queryKey: libraryKeys.conversations(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/conversations", {
          params: { query: { archived: false, limit: 50 } },
          signal,
        });
        if (!data) throw new Error("Conversation list response was empty");
        return data;
      },
    }),
  summary: () =>
    queryOptions({
      queryKey: libraryKeys.summary(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/summary", {
          signal,
        });
        if (!data) throw new Error("Library summary response was empty");
        return data;
      },
    }),
  tags: () =>
    queryOptions({
      queryKey: libraryKeys.tags(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/tags", {
          signal,
        });
        if (!data) throw new Error("Library tag response was empty");
        return data;
      },
    }),
  papers: (
    state: Pick<LibrarySearchState, "cursor" | "query" | "sort" | "tagIds">,
  ) =>
    queryOptions({
      queryKey: libraryKeys.papers(state),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/papers", {
          params: {
            query: {
              cursor: state.cursor,
              limit: 20,
              q: state.query || undefined,
              sort: state.sort as PaperSort,
              tag_ids: state.tagIds.length ? state.tagIds : undefined,
            },
          },
          signal,
        });
        if (!data) throw new Error("Library paper response was empty");
        return data;
      },
      refetchInterval: (query) =>
        query.state.data?.items.some(
          (entry) =>
            entry.entry_type === "ingestion" &&
            ["queued", "processing"].includes(entry.ingestion.state),
        )
          ? 2_000
          : false,
    }),
  outputs: (
    state: Pick<LibrarySearchState, "cursor" | "kinds" | "query" | "sort">,
  ) =>
    queryOptions({
      queryKey: libraryKeys.outputs(state),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/outputs", {
          params: {
            query: {
              cursor: state.cursor,
              kinds: state.kinds.length
                ? (state.kinds as OutputKind[])
                : undefined,
              limit: 20,
              q: state.query || undefined,
              sort: state.sort as OutputSort,
            },
          },
          signal,
        });
        if (!data) throw new Error("Library output response was empty");
        return data;
      },
    }),
};
