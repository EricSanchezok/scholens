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

const populatedHandlers = [
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({ items: libraryConversations, next_cursor: null }),
  ),
  http.get(`${api}/library/summary`, () =>
    HttpResponse.json({ output_count: 8, paper_count: libraryPapers.length }),
  ),
  http.get(`${api}/library/tags`, () =>
    HttpResponse.json({ items: libraryTags, next_cursor: null }),
  ),
  http.get(`${api}/library/papers`, () =>
    HttpResponse.json({
      items: libraryPapers,
      next_cursor: "next-library-page",
      previous_cursor: null,
      total_count: 27,
    }),
  ),
  http.get(`${api}/library/outputs`, () =>
    HttpResponse.json({
      items: libraryOutputs,
      next_cursor: "next-output-page",
      previous_cursor: null,
      total_count: 8,
    }),
  ),
  http.post(`${api}/paper-ingestions/uploads`, () =>
    HttpResponse.json(processingIngestion, { status: 202 }),
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
        next_cursor: "next-library-page",
        previous_cursor: null,
        total_count: 27,
      }),
    ),
    ...populatedHandlers,
  ],
  failed: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({
        items: [failedIngestionEntry, ...libraryPapers],
        next_cursor: "next-library-page",
        previous_cursor: null,
        total_count: 27,
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
