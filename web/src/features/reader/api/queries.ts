import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import { nextAvatarRefreshInterval } from "@/lib/query/avatar-refresh";
import type { components } from "@/lib/api/generated/schema";

type CreateAnnotationRequest =
  components["schemas"]["CreateAnnotationThreadRequest"];
type UpdateAnnotationRequest =
  components["schemas"]["UpdateAnnotationThreadRequest"];
type AnnotationAudienceFilter =
  components["schemas"]["AnnotationAudienceFilter"];
type AnnotationThreadMode = components["schemas"]["AnnotationThreadMode"];
type AnnotationThreadStatus = components["schemas"]["AnnotationThreadStatus"];

type AnnotationListFilters = {
  audience?: AnnotationAudienceFilter;
  mode?: AnnotationThreadMode;
  projectId?: string;
  status: AnnotationThreadStatus;
};

export const readerKeys = {
  all: ["reader"] as const,
  document: (documentId: string) => ["reader", "document", documentId] as const,
  projects: (documentId: string, projectId?: string) =>
    ["reader", "projects", documentId, projectId ?? "personal"] as const,
  annotationLists: (documentId: string) =>
    ["reader", "annotations", documentId] as const,
  annotations: (documentId: string, filters: AnnotationListFilters) =>
    [
      ...readerKeys.annotationLists(documentId),
      filters.projectId ?? "personal",
      filters.audience ?? "all",
      filters.mode ?? "all",
      filters.status,
    ] as const,
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
  projects: (documentId: string, projectId?: string) =>
    queryOptions({
      queryKey: readerKeys.projects(documentId, projectId),
      refetchOnMount: projectId ? "always" : undefined,
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/projects",
          { params: { path: { document_id: documentId } }, signal },
        );
        if (!data) throw new Error("Reader project response was empty");
        return { ...data, verifiedProjectId: projectId ?? null };
      },
    }),
  annotations: (
    documentId: string,
    filters: AnnotationListFilters,
    pollWhenVisible = false,
  ) =>
    queryOptions({
      queryKey: readerKeys.annotations(documentId, filters),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/annotation-threads",
          {
            params: {
              path: { document_id: documentId },
              query: {
                audience: filters.audience,
                mode: filters.mode,
                project_id: filters.projectId,
                status: filters.status,
              },
            },
            signal,
          },
        );
        if (!data) throw new Error("Reader annotation response was empty");
        return data;
      },
      refetchInterval: (query) => {
        const avatarInterval = nextAvatarRefreshInterval(
          query.state.data?.items.flatMap((annotation) => [
            annotation.created_by.avatar,
            annotation.resolved_by?.avatar,
            ...annotation.comments.map((comment) => comment.created_by.avatar),
          ]) ?? [],
        );
        return pollWhenVisible &&
          typeof document !== "undefined" &&
          document.visibilityState === "visible" &&
          document.hasFocus()
          ? Math.min(10_000, avatarInterval)
          : avatarInterval;
      },
      refetchOnWindowFocus: true,
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
