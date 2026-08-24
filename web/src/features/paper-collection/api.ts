import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

export type PaperListPreferences =
  components["schemas"]["PaperListPreferencesResponse"];
export type PaperCollectionColumn = components["schemas"]["PaperListColumn"];
export type PaperCollectionSizedColumn =
  components["schemas"]["PaperListSizedColumn"];
export type PaperStatus = components["schemas"]["PaperStatus"];

export const paperListPreferencesKey = [
  "me",
  "paper-list-preferences",
] as const;

export const defaultPaperListPreferences = {
  column_widths: [
    { column: "paper", width: 360 },
    { column: "status", width: 96 },
    { column: "tags", width: 160 },
    { column: "authors", width: 176 },
    { column: "publication", width: 144 },
    { column: "last_opened", width: 120 },
    { column: "added_at", width: 120 },
    { column: "doi", width: 160 },
  ],
  visible_columns: ["status", "tags", "authors", "publication", "last_opened"],
  preview_open: true,
  preview_width: 512,
} satisfies PaperListPreferences;

export const paperCollectionTagsQuery = () =>
  queryOptions({
    queryKey: ["library", "tags"] as const,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.GET("/api/v1/library/tags", { signal });
      if (!data) throw new Error("Library tag response was empty");
      return data;
    },
  });

export const paperListPreferencesQuery = () =>
  queryOptions({
    queryKey: paperListPreferencesKey,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.GET(
        "/api/v1/me/paper-list-preferences",
        { signal },
      );
      if (!data) throw new Error("Paper list preferences response was empty");
      return data;
    },
  });

export async function updatePaperListPreferences(
  preferences: PaperListPreferences,
) {
  const { data } = await apiClient.PUT("/api/v1/me/paper-list-preferences", {
    body: preferences,
  });
  if (!data) throw new Error("Paper list preferences response was empty");
  return data;
}

export async function updatePaperStatus(
  documentId: string,
  status: PaperStatus,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/library/papers/{document_id}",
    {
      body: { status },
      params: { path: { document_id: documentId } },
    },
  );
  if (!data) throw new Error("Library paper response was empty");
  return data;
}
