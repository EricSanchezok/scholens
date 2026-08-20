import type {
  ProjectDetailSearchState,
  ProjectsSearchState,
} from "../project-search";

export const projectKeys = {
  all: ["projects"] as const,
  lists: () => [...projectKeys.all, "list"] as const,
  list: (state: ProjectsSearchState) =>
    [...projectKeys.lists(), state] as const,
  detail: (projectId: string) =>
    [...projectKeys.all, "detail", projectId] as const,
  members: (projectId: string) =>
    [...projectKeys.detail(projectId), "members"] as const,
  invitations: (projectId: string) =>
    [...projectKeys.detail(projectId), "invitations"] as const,
  papers: (projectId: string, state: ProjectDetailSearchState) =>
    [
      ...projectKeys.detail(projectId),
      "papers",
      state.paperQuery,
      state.paperSort,
    ] as const,
  outputs: (projectId: string, state: ProjectDetailSearchState) =>
    [
      ...projectKeys.detail(projectId),
      "outputs",
      state.outputQuery,
      state.outputKinds,
      state.outputSort,
      state.outputCursor,
    ] as const,
  libraryPapers: () => [...projectKeys.all, "library-papers"] as const,
};
