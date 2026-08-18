import { apiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";

export type KnownPaperSource =
  | { kind: "doi"; value: string }
  | { kind: "arxiv"; value: string }
  | { kind: "url"; value: string };

type IngestionRequestOptions = {
  idempotencyKey: string;
  signal?: AbortSignal;
};

export async function uploadPaperFile(
  file: File,
  contentDigest: string,
  { idempotencyKey, signal }: IngestionRequestOptions,
) {
  const { data: prepared } = await apiClient.POST(
    "/api/v1/paper-ingestions/uploads",
    {
      body: {
        filename: file.name,
        sha256: contentDigest,
        size_bytes: file.size,
        add_to_library: true,
      },
      signal,
    },
  );
  if (!prepared) throw new Error("Paper upload preparation was empty");
  const transferred = await fetch(prepared.upload_url, {
    body: file,
    headers: prepared.headers,
    method: prepared.method,
    signal,
  });
  if (!transferred.ok) {
    throw new ApiError(
      "The PDF could not be transferred to secure staging",
      transferred.status,
      "paper_upload_transfer_failed",
    );
  }
  const { data: ingestion } = await apiClient.POST(
    "/api/v1/paper-ingestions/sources",
    {
      body: {
        source: { kind: "upload", upload_id: prepared.upload_id },
        add_to_library: true,
      },
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
    },
  );
  if (!ingestion) throw new Error("Paper ingestion response was empty");
  return ingestion;
}

export async function uploadPaperSource(
  source: KnownPaperSource,
  { idempotencyKey, signal }: IngestionRequestOptions,
) {
  const normalized =
    source.kind === "doi"
      ? { kind: source.kind, doi: source.value }
      : source.kind === "arxiv"
        ? { kind: source.kind, arxiv_id: source.value }
        : { kind: source.kind, url: source.value };
  const { data } = await apiClient.POST("/api/v1/paper-ingestions/sources", {
    body: { source: normalized, add_to_library: true },
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
