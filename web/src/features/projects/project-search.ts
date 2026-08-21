import { z } from "zod";

const projectSortSchema = z.enum(["activity_desc", "title_asc", "papers_desc"]);
const projectViewSchema = z.enum(["overview", "papers", "outputs"]);
const paperSortSchema = z.enum([
  "added_desc",
  "title_asc",
  "published_desc",
  "personal_activity_desc",
]);
const paperStatusSchema = z.enum(["todo", "reading", "completed"]);
const outputSortSchema = z.enum([
  "updated_desc",
  "updated_asc",
  "title_asc",
  "title_desc",
]);
const outputKindSchema = z.enum([
  "annotation_thread",
  "citation",
  "audio_overview",
  "data_table",
]);

export type ProjectSort = z.infer<typeof projectSortSchema>;
export type ProjectView = z.infer<typeof projectViewSchema>;
export type ProjectPaperSort = z.infer<typeof paperSortSchema>;
export type ProjectOutputSort = z.infer<typeof outputSortSchema>;
export type ProjectOutputKind = z.infer<typeof outputKindSchema>;

export type ProjectsSearchState = {
  query: string;
  sort: ProjectSort;
  cursor?: string;
};

export type ProjectDetailSearchState = {
  view: ProjectView;
  conversation?: string;
  panel?: "chat";
  paperQuery: string;
  paperSort: ProjectPaperSort;
  paperCursor?: string;
  paperStatuses: z.infer<typeof paperStatusSchema>[];
  paperTagIds: string[];
  outputQuery: string;
  outputKinds: ProjectOutputKind[];
  outputSort: ProjectOutputSort;
  outputCursor?: string;
};

function optionalValue(value: string | null) {
  return value?.trim() || undefined;
}

export function parseProjectsSearch(
  params: URLSearchParams,
): ProjectsSearchState {
  return {
    query: params.get("q")?.trim() ?? "",
    sort: projectSortSchema.catch("activity_desc").parse(params.get("sort")),
    cursor: optionalValue(params.get("cursor")),
  };
}

export function serializeProjectsSearch(state: ProjectsSearchState) {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.sort !== "activity_desc") params.set("sort", state.sort);
  if (state.cursor) params.set("cursor", state.cursor);
  return params;
}

export function parseProjectDetailSearch(
  params: URLSearchParams,
): ProjectDetailSearchState {
  return {
    view: projectViewSchema.catch("overview").parse(params.get("view")),
    conversation: optionalValue(params.get("conversation")),
    panel: params.get("panel") === "chat" ? "chat" : undefined,
    paperQuery: params.get("paper_q")?.trim() ?? "",
    paperSort: paperSortSchema
      .catch("added_desc")
      .parse(params.get("paper_sort")),
    paperCursor: optionalValue(params.get("paper_cursor")),
    paperStatuses: params
      .getAll("paper_status")
      .map((value) => paperStatusSchema.safeParse(value))
      .filter((result) => result.success)
      .map((result) => result.data),
    paperTagIds: params.getAll("paper_tag").filter(Boolean),
    outputQuery: params.get("output_q")?.trim() ?? "",
    outputKinds: params
      .getAll("output_kind")
      .map((value) => outputKindSchema.safeParse(value))
      .filter((result) => result.success)
      .map((result) => result.data),
    outputSort: outputSortSchema
      .catch("updated_desc")
      .parse(params.get("output_sort")),
    outputCursor: optionalValue(params.get("output_cursor")),
  };
}

export function serializeProjectDetailSearch(state: ProjectDetailSearchState) {
  const params = new URLSearchParams();
  if (state.view !== "overview") params.set("view", state.view);
  if (state.conversation) params.set("conversation", state.conversation);
  if (state.panel) params.set("panel", state.panel);
  if (state.paperQuery) params.set("paper_q", state.paperQuery);
  if (state.paperSort !== "added_desc")
    params.set("paper_sort", state.paperSort);
  if (state.paperCursor) params.set("paper_cursor", state.paperCursor);
  for (const status of state.paperStatuses)
    params.append("paper_status", status);
  for (const tagId of state.paperTagIds) params.append("paper_tag", tagId);
  if (state.outputQuery) params.set("output_q", state.outputQuery);
  for (const kind of state.outputKinds) params.append("output_kind", kind);
  if (state.outputSort !== "updated_desc")
    params.set("output_sort", state.outputSort);
  if (state.outputCursor) params.set("output_cursor", state.outputCursor);
  return params;
}
