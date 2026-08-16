import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

export type ZoteroConnectionStatus =
  components["schemas"]["ZoteroConnectionStatus"];
export type ZoteroLibraryItem = components["schemas"]["ZoteroLibraryItem"];
export type ZoteroLibraryPage = components["schemas"]["ZoteroLibraryPage"];
export type ZoteroOperation = components["schemas"]["ZoteroOperation"];

export type ZoteroLibraryFilters = {
  collectionKey?: string;
  cursor?: string;
  itemType?: "journalArticle" | "conferencePaper" | "preprint";
  query?: string;
  sort:
    | "modified_desc"
    | "added_desc"
    | "published_desc"
    | "title_asc"
    | "creator_asc";
};

export const zoteroKeys = {
  all: ["zotero"] as const,
  status: () => ["zotero", "status"] as const,
  collections: () => ["zotero", "collections"] as const,
  library: (filters: ZoteroLibraryFilters) =>
    ["zotero", "library", filters] as const,
  operation: (kind: "import" | "sync", id: string) =>
    ["zotero", "operation", kind, id] as const,
};

export const zoteroQueries = {
  status: () =>
    queryOptions({
      queryKey: zoteroKeys.status(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/integrations/zotero/status",
          { signal },
        );
        if (!data) throw new Error("Zotero status response was empty");
        return data;
      },
    }),
  collections: () =>
    infiniteQueryOptions({
      queryKey: zoteroKeys.collections(),
      initialPageParam: undefined as string | undefined,
      queryFn: async ({ pageParam, signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/integrations/zotero/collections",
          {
            params: { query: { cursor: pageParam, limit: 100 } },
            signal,
          },
        );
        if (!data) throw new Error("Zotero collections response was empty");
        return data;
      },
      getNextPageParam: (page) => page.next_cursor ?? undefined,
    }),
  library: (filters: ZoteroLibraryFilters) =>
    queryOptions({
      queryKey: zoteroKeys.library(filters),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/integrations/zotero/library-items",
          {
            params: {
              query: {
                collection_key: filters.collectionKey,
                cursor: filters.cursor,
                item_type: filters.itemType,
                limit: 25,
                query: filters.query || undefined,
                sort: filters.sort,
              },
            },
            signal,
          },
        );
        if (!data) throw new Error("Zotero library response was empty");
        return data;
      },
    }),
  operation: (kind: "import" | "sync", id: string) =>
    queryOptions({
      queryKey: zoteroKeys.operation(kind, id),
      queryFn: async ({ signal }) => {
        const path =
          kind === "import"
            ? "/api/v1/integrations/zotero/imports/{operation_id}"
            : "/api/v1/integrations/zotero/sync-runs/{operation_id}";
        const { data } =
          kind === "import"
            ? await apiClient.GET(path, {
                params: { path: { operation_id: id } },
                signal,
              })
            : await apiClient.GET(path, {
                params: { path: { operation_id: id } },
                signal,
              });
        if (!data) throw new Error("Zotero operation response was empty");
        return data;
      },
      refetchInterval: (query) =>
        query.state.data &&
        ["queued", "running"].includes(query.state.data.status)
          ? 1_500
          : false,
    }),
};

export async function beginZoteroAuthorization(
  intent: "manage" | "import",
  returnPath: string,
) {
  const { data } = await apiClient.POST(
    "/api/v1/integrations/zotero/oauth/authorizations",
    { body: { intent, return_path: returnPath } },
  );
  if (!data) throw new Error("Zotero authorization response was empty");
  return data;
}

export async function disconnectZotero() {
  await apiClient.DELETE("/api/v1/integrations/zotero/connection");
}

export async function updateZoteroSyncPreferences(autoImportEnabled: boolean) {
  const { data } = await apiClient.PUT(
    "/api/v1/integrations/zotero/sync-preferences",
    { body: { auto_import_enabled: autoImportEnabled } },
  );
  if (!data) throw new Error("Zotero preference response was empty");
  return data;
}

export async function startZoteroImport(itemKeys: string[]) {
  const { data } = await apiClient.POST("/api/v1/integrations/zotero/imports", {
    body: { item_keys: itemKeys },
    params: {
      header: { "Idempotency-Key": crypto.randomUUID() },
    },
  });
  if (!data) throw new Error("Zotero import response was empty");
  return data;
}

export async function cancelZoteroImport(operationId: string) {
  const { data } = await apiClient.DELETE(
    "/api/v1/integrations/zotero/imports/{operation_id}",
    { params: { path: { operation_id: operationId } } },
  );
  if (!data) throw new Error("Zotero cancellation response was empty");
  return data;
}

export async function cancelZoteroSync(operationId: string) {
  const { data } = await apiClient.DELETE(
    "/api/v1/integrations/zotero/sync-runs/{operation_id}",
    { params: { path: { operation_id: operationId } } },
  );
  if (!data) throw new Error("Zotero cancellation response was empty");
  return data;
}

export async function startZoteroSync() {
  const { data } = await apiClient.POST(
    "/api/v1/integrations/zotero/sync-runs",
    {
      params: { header: { "Idempotency-Key": crypto.randomUUID() } },
    },
  );
  if (!data) throw new Error("Zotero sync response was empty");
  return data;
}
