import type { LibrarySearchState } from "../library-search";

export const libraryKeys = {
  all: ["library"] as const,
  summary: () => [...libraryKeys.all, "summary"] as const,
  tags: () => [...libraryKeys.all, "tags"] as const,
  papers: (
    state: Pick<LibrarySearchState, "query" | "sort" | "statuses" | "tagIds">,
  ) => [...libraryKeys.all, "papers", state] as const,
  outputs: (
    state: Pick<LibrarySearchState, "cursor" | "kinds" | "query" | "sort">,
  ) => [...libraryKeys.all, "outputs", state] as const,
};
