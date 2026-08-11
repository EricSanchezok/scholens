import type { components } from "@/lib/api/generated/schema";
import { apiClient } from "@/lib/api";

type PaperSource = components["schemas"]["UploadFromSourceRequest"]["source"];

type IngestionRequestOptions = {
  idempotencyKey: string;
  projectId?: string;
  signal?: AbortSignal;
};

export async function uploadPaperFile(
  file: File,
  { idempotencyKey, projectId, signal }: IngestionRequestOptions,
) {
  const { data } = await apiClient.POST("/api/v1/paper-ingestions/uploads", {
    body: { file: file as unknown as string },
    bodySerializer: () => {
      const form = new FormData();
      form.append("file", file);
      return form;
    },
    headers: { "Idempotency-Key": idempotencyKey },
    params: { query: { project_id: projectId } },
    signal,
  });
  if (!data) throw new Error("Paper upload response was empty");
  return data;
}

export async function uploadPaperSource(
  source: PaperSource,
  { idempotencyKey, projectId, signal }: IngestionRequestOptions,
) {
  const { data } = await apiClient.POST("/api/v1/paper-ingestions/sources", {
    body: { project_id: projectId, source },
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

export async function assignLibraryTags(
  documentIds: string[],
  tagIds: string[],
) {
  const { data } = await apiClient.POST("/api/v1/library/tags/assignments", {
    body: { document_ids: documentIds, tag_ids: tagIds },
  });
  if (!data) throw new Error("Tag assignment response was empty");
  return data;
}

export async function addPapersToProject(
  projectId: string,
  documentIds: string[],
) {
  const { data } = await apiClient.POST(
    "/api/v1/projects/{project_id}/papers",
    {
      body: { document_ids: documentIds },
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) throw new Error("Project paper response was empty");
  return data;
}

export async function getPaperDownloadUrl(documentId: string) {
  const { data } = await apiClient.GET(
    "/api/v1/papers/{document_id}/download-url",
    { params: { path: { document_id: documentId } } },
  );
  if (!data) throw new Error("Paper download response was empty");
  return data;
}
