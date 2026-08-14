import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import { homeKeys } from "./keys";

export const homeQueries = {
  papers: () =>
    queryOptions({
      queryKey: homeKeys.papers(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/library/papers", {
          signal,
        });
        if (!data) throw new Error("Library response was empty");
        return data;
      },
    }),
  projects: () =>
    queryOptions({
      queryKey: homeKeys.projects(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/projects", {
          params: { query: { limit: 12 } },
          signal,
        });
        if (!data) throw new Error("Project list response was empty");
        return data;
      },
    }),
};
