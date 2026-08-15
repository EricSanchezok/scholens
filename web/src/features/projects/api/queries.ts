import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type {
  ProjectDetailSearchState,
  ProjectsSearchState,
} from "../project-search";
import { projectKeys } from "./keys";

export const projectQueries = {
  list: (state: ProjectsSearchState) =>
    queryOptions({
      queryKey: projectKeys.list(state),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/projects", {
          params: {
            query: {
              cursor: state.cursor,
              limit: 20,
              q: state.query || undefined,
              sort: state.sort,
            },
          },
          signal,
        });
        if (!data) throw new Error("Project list response was empty");
        return data;
      },
    }),
  detail: (projectId: string) =>
    queryOptions({
      queryKey: projectKeys.detail(projectId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/projects/{project_id}", {
          params: { path: { project_id: projectId } },
          signal,
        });
        if (!data) throw new Error("Project response was empty");
        return data;
      },
    }),
  papers: (projectId: string, state: ProjectDetailSearchState) =>
    queryOptions({
      queryKey: projectKeys.papers(projectId, state),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/papers",
          {
            params: {
              path: { project_id: projectId },
              query: {
                cursor: state.paperCursor,
                limit: 20,
                load_urls: false,
                q: state.paperQuery || undefined,
                sort: state.paperSort,
              },
            },
            signal,
          },
        );
        if (!data) throw new Error("Project paper response was empty");
        return data;
      },
    }),
  outputs: (projectId: string, state: ProjectDetailSearchState) =>
    queryOptions({
      queryKey: projectKeys.outputs(projectId, state),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/outputs",
          {
            params: {
              path: { project_id: projectId },
              query: {
                cursor: state.outputCursor,
                kinds: state.outputKinds.length ? state.outputKinds : undefined,
                limit: 20,
                q: state.outputQuery || undefined,
                sort: state.outputSort,
              },
            },
            signal,
          },
        );
        if (!data) throw new Error("Project output response was empty");
        return data;
      },
    }),
  libraryPapers: () =>
    queryOptions({
      queryKey: projectKeys.libraryPapers(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/papers", {
          params: { query: { limit: 100, sort: "added_desc" } },
          signal,
        });
        if (!data) throw new Error("Library paper response was empty");
        return data;
      },
    }),
};
