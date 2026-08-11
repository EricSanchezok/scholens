import { delay, http, HttpResponse } from "msw";

import {
  failedJob,
  libraryConversations,
  libraryOutputs,
  libraryPapers,
  libraryProjects,
  libraryTags,
  processingJob,
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
  http.get(`${api}/projects`, () =>
    HttpResponse.json({ items: libraryProjects, next_cursor: null }),
  ),
  http.get(`${api}/jobs`, () =>
    HttpResponse.json({ items: [], next_cursor: null }),
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
    HttpResponse.json(processingJob, { status: 201 }),
  ),
  http.post(`${api}/paper-ingestions/sources`, () =>
    HttpResponse.json(processingJob, { status: 201 }),
  ),
  http.post(`${api}/paper-ingestions/:jobId/retries`, () =>
    HttpResponse.json(processingJob, { status: 201 }),
  ),
  http.post(`${api}/library/paper-removals`, async ({ request }) => {
    const body = (await request.json()) as { document_ids: string[] };
    return HttpResponse.json({ removed_document_ids: body.document_ids });
  }),
  http.post(`${api}/library/tags/assignments`, () =>
    HttpResponse.json({ assigned_count: 1 }),
  ),
  http.post(`${api}/projects/:projectId/papers`, () =>
    HttpResponse.json({
      added_document_ids: [libraryPapers[0]!.document.document_id],
    }),
  ),
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
    http.get(`${api}/jobs`, () =>
      HttpResponse.json({ items: [processingJob], next_cursor: null }),
    ),
    ...populatedHandlers,
  ],
  failed: [
    http.get(`${api}/jobs`, () =>
      HttpResponse.json({ items: [failedJob], next_cursor: null }),
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
