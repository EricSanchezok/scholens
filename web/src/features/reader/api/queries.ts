import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";

export const readerKeys = {
  all: ["reader"] as const,
  document: (documentId: string) => ["reader", "document", documentId] as const,
  annotations: (documentId: string) =>
    ["reader", "annotations", documentId] as const,
};

export const readerQueries = {
  document: (documentId: string) =>
    queryOptions({
      queryKey: readerKeys.document(documentId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/papers/{document_id}", {
          params: { path: { document_id: documentId } },
          signal,
        });
        if (!data) throw new Error("Reader document response was empty");
        return data;
      },
      refetchInterval: (query) => {
        const status = query.state.data?.processing_status;
        return status === "pending" || status === "processing" ? 1_500 : false;
      },
    }),
  annotations: (documentId: string) =>
    queryOptions({
      queryKey: readerKeys.annotations(documentId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/highlight-threads",
          { params: { path: { document_id: documentId } }, signal },
        );
        if (!data) throw new Error("Reader annotation response was empty");
        return data;
      },
    }),
};

export async function getReaderDownloadUrl(documentId: string) {
  const { data } = await apiClient.GET(
    "/api/v1/papers/{document_id}/download-url",
    { params: { path: { document_id: documentId } } },
  );
  if (!data) throw new Error("Reader download response was empty");
  return data.file_url;
}
