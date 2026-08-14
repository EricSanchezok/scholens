import type { components } from "@/lib/api/generated/schema";
import { apiClient } from "@/lib/api";

type PaperSource = components["schemas"]["UploadFromSourceRequest"]["source"];

type IngestionRequestOptions = {
  idempotencyKey: string;
  signal?: AbortSignal;
};

export async function uploadPaperFile(
  file: File,
  { idempotencyKey, signal }: IngestionRequestOptions,
) {
  const { data } = await apiClient.POST("/api/v1/paper-ingestions/uploads", {
    body: { file: file as unknown as string },
    bodySerializer: () => {
      const form = new FormData();
      form.append("file", file);
      return form;
    },
    headers: { "Idempotency-Key": idempotencyKey },
    params: { query: {} },
    signal,
  });
  if (!data) throw new Error("Paper upload response was empty");
  return data;
}

export async function uploadPaperSource(
  source: PaperSource,
  { idempotencyKey, signal }: IngestionRequestOptions,
) {
  const { data } = await apiClient.POST("/api/v1/paper-ingestions/sources", {
    body: { source },
    headers: { "Idempotency-Key": idempotencyKey },
    signal,
  });
  if (!data) throw new Error("Paper source response was empty");
  return data;
}

export async function retryPaperIngestion(
  jobId: string,
  idempotencyKey: string,
) {
  const { data } = await apiClient.POST(
    "/api/v1/paper-ingestions/{job_id}/retries",
    {
      headers: { "Idempotency-Key": idempotencyKey },
      params: { path: { job_id: jobId } },
    },
  );
  if (!data) throw new Error("Paper retry response was empty");
  return data;
}

export async function cancelPaperIngestion(
  jobId: string,
  signal?: AbortSignal,
) {
  await apiClient.DELETE("/api/v1/paper-ingestions/{job_id}", {
    params: { path: { job_id: jobId } },
    signal,
  });
}

export async function removeLibraryPapers(documentIds: string[]) {
  const { data } = await apiClient.POST("/api/v1/library/paper-removals", {
    body: { document_ids: documentIds },
  });
  if (!data) throw new Error("Paper removal response was empty");
  return data;
}

export async function replaceLibraryTagAssignments(
  documentIds: string[],
  tagIds: string[],
) {
  const { data } = await apiClient.PUT("/api/v1/library/tags/assignments", {
    body: { document_ids: documentIds, tag_ids: tagIds },
  });
  if (!data) throw new Error("Tag assignment response was empty");
  return data;
}

export async function createLibraryTag(name: string) {
  const { data } = await apiClient.POST("/api/v1/library/tags", {
    body: { name },
  });
  if (!data) throw new Error("Tag creation response was empty");
  return data;
}

export async function renameLibraryTag(tagId: string, name: string) {
  const { data } = await apiClient.PATCH("/api/v1/library/tags/{tag_id}", {
    body: { name },
    params: { path: { tag_id: tagId } },
  });
  if (!data) throw new Error("Tag rename response was empty");
  return data;
}

export async function deleteLibraryTag(tagId: string) {
  await apiClient.DELETE("/api/v1/library/tags/{tag_id}", {
    params: { path: { tag_id: tagId } },
  });
}

export async function getPaperDownloadUrl(documentId: string) {
  const { data } = await apiClient.GET(
    "/api/v1/papers/{document_id}/download-url",
    { params: { path: { document_id: documentId } } },
  );
  if (!data) throw new Error("Paper download response was empty");
  return data;
}
