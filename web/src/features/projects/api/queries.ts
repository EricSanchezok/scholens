import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

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
  members: (projectId: string) =>
    queryOptions({
      queryKey: projectKeys.members(projectId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/members",
          {
            params: { path: { project_id: projectId } },
            signal,
          },
        );
        if (!data) throw new Error("Project member response was empty");
        return data;
      },
    }),
  invitations: (projectId: string) =>
    queryOptions({
      queryKey: projectKeys.invitations(projectId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/invitations",
          {
            params: { path: { project_id: projectId } },
            signal,
          },
        );
        if (!data) throw new Error("Project invitation response was empty");
        return data;
      },
      refetchInterval: (query) =>
        query.state.data?.items.some(
          (invitation) => invitation.delivery_status === "pending",
        )
          ? 2_000
          : false,
    }),
  papers: (projectId: string, state: ProjectDetailSearchState) =>
    infiniteQueryOptions({
      queryKey: projectKeys.papers(projectId, state),
      initialPageParam: undefined as string | undefined,
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/papers",
          {
            params: {
              path: { project_id: projectId },
              query: {
                cursor: pageParam,
                limit: 20,
                load_urls: false,
                load_preview_urls: true,
                q: state.paperQuery || undefined,
                sort: state.paperSort,
                personal_statuses: state.paperStatuses.length
                  ? state.paperStatuses
                  : undefined,
                personal_tag_ids: state.paperTagIds.length
                  ? state.paperTagIds
                  : undefined,
              },
            },
            signal,
          },
        );
        if (!data) throw new Error("Project paper response was empty");
        return data;
      },
      getNextPageParam: (page) => page.next_cursor ?? undefined,
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
