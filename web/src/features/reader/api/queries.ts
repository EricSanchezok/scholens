import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

type CreateAnnotationRequest =
  components["schemas"]["CreateAnnotationThreadRequest"];
type UpdateAnnotationRequest =
  components["schemas"]["UpdateAnnotationThreadRequest"];

export const readerKeys = {
  all: ["reader"] as const,
  document: (documentId: string) => ["reader", "document", documentId] as const,
  annotations: (documentId: string, projectId?: string) =>
    ["reader", "annotations", documentId, projectId ?? "personal"] as const,
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
  annotations: (documentId: string, projectId?: string) =>
    queryOptions({
      queryKey: readerKeys.annotations(documentId, projectId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/annotation-threads",
          {
            params: {
              path: { document_id: documentId },
              query: { project_id: projectId },
            },
            signal,
          },
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

export async function createReaderAnnotationThread(
  documentId: string,
  body: CreateAnnotationRequest,
) {
  const { data } = await apiClient.POST(
    "/api/v1/papers/{document_id}/annotation-threads",
    { params: { path: { document_id: documentId } }, body },
  );
  if (!data) throw new Error("Create highlight response was empty");
  return data;
}

export async function updateReaderAnnotationThread(
  threadId: string,
  body: UpdateAnnotationRequest,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/annotation-threads/{thread_id}",
    { params: { path: { thread_id: threadId } }, body },
  );
  if (!data) throw new Error("Update highlight response was empty");
  return data;
}

export async function deleteReaderAnnotationThread(threadId: string) {
  await apiClient.DELETE("/api/v1/annotation-threads/{thread_id}", {
    params: { path: { thread_id: threadId } },
  });
}

export async function createReaderComment(threadId: string, content: string) {
  const { data } = await apiClient.POST(
    "/api/v1/annotation-threads/{thread_id}/comments",
    {
      params: { path: { thread_id: threadId } },
      body: { content },
    },
  );
  if (!data) throw new Error("Create annotation comment response was empty");
  return data;
}

export async function updateReaderComment(commentId: string, content: string) {
  const { data } = await apiClient.PATCH(
    "/api/v1/annotation-comments/{comment_id}",
    {
      params: { path: { comment_id: commentId } },
      body: { content },
    },
  );
  if (!data) throw new Error("Update annotation comment response was empty");
  return data;
}

export async function deleteReaderComment(commentId: string) {
  await apiClient.DELETE("/api/v1/annotation-comments/{comment_id}", {
    params: { path: { comment_id: commentId } },
  });
}

export async function setReaderConversationPinned(
  conversationId: string,
  pinned: boolean,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/conversations/{conversation_id}",
    {
      params: { path: { conversation_id: conversationId } },
      body: { pinned },
    },
  );
  if (!data) throw new Error("Update conversation response was empty");
  return data;
}
