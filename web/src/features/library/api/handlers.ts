import { delay, http, HttpResponse } from "msw";

import {
  failedIngestionEntry,
  libraryConversations,
  libraryLongTitlePapers,
  libraryOutputs,
  libraryPapers,
  libraryTags,
  processingIngestion,
  processingIngestionEntry,
} from "./fixtures";

const api = "http://127.0.0.1:7301/api/v1";

const nextLibraryPage = libraryPapers.map((paper, index) => {
  const suffix = String(index + 101).padStart(12, "0");
  const documentId = `70000000-0000-4000-8000-${suffix}`;
  return {
    ...paper,
    document: {
      ...paper.document,
      document_id: documentId,
      title: `Follow-up reading ${index + 1}: ${paper.document.title}`,
    },
    library_entry_id: `72000000-0000-4000-8000-${suffix}`,
  };
});

const populatedHandlers = [
  http.get(`${api}/integrations/zotero/status`, () =>
    HttpResponse.json({
      active_operation_id: null,
      active_operation_kind: null,
      auto_import_enabled: false,
      auto_import_state: "off",
      automatic_annotation_sync: "off",
      automatic_sync_eligible: false,
      connected_at: null,
      connection_state: "disconnected",
      last_error_code: null,
      last_successful_sync_at: null,
    }),
  ),
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({ items: libraryConversations, next_cursor: null }),
  ),
  http.get(`${api}/library/summary`, () =>
    HttpResponse.json({
      attention_count: 0,
      ingestion_count: 0,
      output_count: 8,
      paper_count: libraryPapers.length,
    }),
  ),
  http.get(`${api}/library/tags`, () =>
    HttpResponse.json({ items: libraryTags, next_cursor: null }),
  ),
  http.get(`${api}/library/papers`, ({ request }) => {
    const cursor = new URL(request.url).searchParams.get("cursor");
    return HttpResponse.json({
      items: cursor ? nextLibraryPage : libraryPapers,
      next_cursor: cursor ? null : "next-library-page",
      previous_cursor: null,
      total_count: 6,
    });
  }),
  http.get(`${api}/library/outputs`, () =>
    HttpResponse.json({
      items: libraryOutputs,
      next_cursor: "next-output-page",
      previous_cursor: null,
      total_count: 8,
    }),
  ),
  http.post(`${api}/paper-ingestions/uploads`, () =>
    HttpResponse.json(
      {
        headers: {
          "content-type": "application/pdf",
          "x-amz-checksum-sha256": "test-checksum",
        },
        max_bytes: 31_457_280,
        method: "PUT",
        next_step: "upload_pdf_then_call_ingest_paper_with_upload_id",
        session_expires_at: "2026-08-17T02:00:00Z",
        upload_id: "00000000-0000-4000-8000-000000000088",
        upload_url: "http://127.0.0.1:7301/mock-paper-upload",
        upload_url_expires_at: "2026-08-16T02:15:00Z",
      },
      { status: 201 },
    ),
  ),
  http.put(
    `${api.replace("/api/v1", "")}/mock-paper-upload`,
    () => new HttpResponse(null, { status: 200 }),
  ),
  http.post(`${api}/paper-ingestions/sources`, () =>
    HttpResponse.json(processingIngestion, { status: 202 }),
  ),
  http.post(`${api}/paper-ingestions/:jobId/retries`, () =>
    HttpResponse.json(processingIngestion, { status: 202 }),
  ),
  http.delete(
    `${api}/paper-ingestions/:jobId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post(`${api}/library/paper-removals`, async ({ request }) => {
    const body = (await request.json()) as { document_ids: string[] };
    return HttpResponse.json({ removed_document_ids: body.document_ids });
  }),
  http.post(`${api}/library/tags`, async ({ request }) => {
    const body = (await request.json()) as { name: string };
    return HttpResponse.json(
      { color: null, id: crypto.randomUUID(), name: body.name },
      { status: 201 },
    );
  }),
  http.patch(`${api}/library/tags/:tagId`, async ({ params, request }) => {
    const body = (await request.json()) as { name: string };
    return HttpResponse.json({
      color: null,
      id: String(params.tagId),
      name: body.name,
    });
  }),
  http.delete(
    `${api}/library/tags/:tagId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.put(`${api}/library/tags/assignments`, async ({ request }) => {
    const body = (await request.json()) as { document_ids: string[] };
    return HttpResponse.json({ updated_paper_count: body.document_ids.length });
  }),
  http.get(`${api}/papers/:documentId/download-url`, () =>
    HttpResponse.json({ file_url: "https://example.org/paper.pdf" }),
  ),
];

export const libraryHandlers = {
  populated: populatedHandlers,
  openAlexRequired: [
    http.post(`${api}/paper-ingestions/sources`, () =>
      HttpResponse.json(
        {
          code: "openalex_credential_required",
          details: { required_integration: "openalex" },
          message: "A connected OpenAlex API key is required",
          retryable: true,
        },
        { status: 409 },
      ),
    ),
    http.get(`${api}/me/integrations`, () =>
      HttpResponse.json({
        items: [
          {
            category: "built_in",
            enabled: true,
            managed: true,
            provider: "scholight",
            state: "connected",
          },
          {
            category: "search",
            enabled: false,
            managed: false,
            provider: "openalex",
            state: "disconnected",
          },
        ],
      }),
    ),
    ...populatedHandlers,
  ],
  empty: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    ),
    ...populatedHandlers,
  ],
  loading: [
    http.get(`${api}/library/papers`, async () => {
      await delay("infinite");
      return HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      });
    }),
    ...populatedHandlers,
  ],
  error: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    ...populatedHandlers,
  ],
  processing: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({
        items: [processingIngestionEntry, ...libraryPapers],
        next_cursor: null,
        previous_cursor: null,
        total_count: libraryPapers.length + 1,
      }),
    ),
    ...populatedHandlers,
  ],
  failed: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({
        items: [failedIngestionEntry, ...libraryPapers],
        next_cursor: null,
        previous_cursor: null,
        total_count: libraryPapers.length + 1,
      }),
    ),
    ...populatedHandlers,
  ],
  longTitles: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({
        items: libraryLongTitlePapers,
        next_cursor: null,
        previous_cursor: null,
        total_count: libraryLongTitlePapers.length,
      }),
    ),
    ...populatedHandlers,
  ],
  outputsEmpty: [
    http.get(`${api}/library/outputs`, () =>
      HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    ),
    ...populatedHandlers,
  ],
  outputsLoading: [
    http.get(`${api}/library/outputs`, async () => {
      await delay("infinite");
      return HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      });
    }),
    ...populatedHandlers,
  ],
  outputsError: [
    http.get(`${api}/library/outputs`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    ...populatedHandlers,
  ],
};
