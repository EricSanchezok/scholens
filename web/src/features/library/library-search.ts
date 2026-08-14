import { z } from "zod";

export const libraryTabSchema = z.enum(["papers", "outputs"]);
export type LibraryTab = z.infer<typeof libraryTabSchema>;

export const paperSortSchema = z.enum([
  "added_desc",
  "added_asc",
  "published_desc",
  "published_asc",
  "title_asc",
]);
export type PaperSort = z.infer<typeof paperSortSchema>;

export const outputSortSchema = z.enum([
  "updated_desc",
  "updated_asc",
  "title_asc",
  "title_desc",
]);
export type OutputSort = z.infer<typeof outputSortSchema>;

export const outputKindSchema = z.enum([
  "annotation_thread",
  "citation",
  "audio_overview",
  "data_table",
]);
export type OutputKind = z.infer<typeof outputKindSchema>;

export type LibrarySearchState = {
  cursor?: string;
  kinds: OutputKind[];
  query: string;
  sort: PaperSort | OutputSort;
  tab: LibraryTab;
  tagIds: string[];
};

function values(params: URLSearchParams, key: string) {
  return params
    .getAll(key)
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);
}

export function parseLibrarySearch(
  params: URLSearchParams,
): LibrarySearchState {
  const tab = libraryTabSchema.catch("papers").parse(params.get("tab"));
  const paperSort = paperSortSchema.safeParse(params.get("sort"));
  const outputSort = outputSortSchema.safeParse(params.get("sort"));
  const kinds = values(params, "kind").flatMap((value) => {
    const parsed = outputKindSchema.safeParse(value);
    return parsed.success ? [parsed.data] : [];
  });
  return {
    cursor: params.get("cursor") || undefined,
    kinds,
    query: params.get("q")?.trim() ?? "",
    sort:
      tab === "outputs"
        ? outputSort.success
          ? outputSort.data
          : "updated_desc"
        : paperSort.success
          ? paperSort.data
          : "added_desc",
    tab,
    tagIds: values(params, "tag"),
  };
}

export function serializeLibrarySearch(state: LibrarySearchState) {
  const params = new URLSearchParams();
  if (state.tab !== "papers") params.set("tab", state.tab);
  if (state.query) params.set("q", state.query);
  const defaultSort = state.tab === "papers" ? "added_desc" : "updated_desc";
  if (state.sort !== defaultSort) params.set("sort", state.sort);
  state.tagIds.forEach((tagId) => params.append("tag", tagId));
  state.kinds.forEach((kind) => params.append("kind", kind));
  if (state.cursor) params.set("cursor", state.cursor);
  return params;
}
