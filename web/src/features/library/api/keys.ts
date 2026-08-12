import type { LibrarySearchState } from "../library-search";

export const libraryKeys = {
  all: ["library"] as const,
  conversations: () => [...libraryKeys.all, "conversations"] as const,
  summary: () => [...libraryKeys.all, "summary"] as const,
  tags: () => [...libraryKeys.all, "tags"] as const,
  papers: (
    state: Pick<LibrarySearchState, "cursor" | "query" | "sort" | "tagIds">,
  ) => [...libraryKeys.all, "papers", state] as const,
  outputs: (
    state: Pick<LibrarySearchState, "cursor" | "kinds" | "query" | "sort">,
  ) => [...libraryKeys.all, "outputs", state] as const,
};
