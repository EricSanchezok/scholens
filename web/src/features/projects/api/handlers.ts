import { delay, http, HttpResponse } from "msw";

import {
  projectConversationFixtures,
  projectFixtures,
  projectLibraryPaperFixtures,
  projectOutputFixtures,
  projectPaperFixtures,
} from "./fixtures";

const api = "http://127.0.0.1:7301/api/v1";

const populated = [
  http.get(`${api}/projects`, () =>
    HttpResponse.json({
      items: projectFixtures,
      next_cursor: null,
      previous_cursor: null,
      total_count: projectFixtures.length,
    }),
  ),
  http.get(`${api}/projects/:projectId`, () =>
    HttpResponse.json(projectFixtures[0]),
  ),
  http.get(`${api}/projects/:projectId/papers`, () =>
    HttpResponse.json({
      items: projectPaperFixtures,
      next_cursor: null,
      previous_cursor: null,
      total_count: projectPaperFixtures.length,
    }),
  ),
  http.get(`${api}/projects/:projectId/outputs`, () =>
    HttpResponse.json({
      items: projectOutputFixtures,
      next_cursor: null,
      previous_cursor: null,
      total_count: projectOutputFixtures.length,
    }),
  ),
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({
      items: projectConversationFixtures,
      next_cursor: null,
    }),
  ),
  http.get(`${api}/conversations/:conversationId`, ({ params }) => {
    const conversation = projectConversationFixtures.find(
      (item) => item.id === params.conversationId,
    );
    return HttpResponse.json({
      ...(conversation ?? projectConversationFixtures[0]),
      paper_context: { kind: "library" },
      tool_permissions: [],
    });
  }),
  http.get(`${api}/conversations/:conversationId/turns`, () =>
    HttpResponse.json({ items: [], next_cursor: null, path_revision: 1 }),
  ),
  http.patch(`${api}/conversations/:conversationId`, ({ params }) => {
    const conversation = projectConversationFixtures.find(
      (item) => item.id === params.conversationId,
    );
    return HttpResponse.json(conversation ?? projectConversationFixtures[0]);
  }),
  http.get(`${api}/library/papers`, () =>
    HttpResponse.json({
      items: projectLibraryPaperFixtures,
      next_cursor: null,
      previous_cursor: null,
      total_count: projectLibraryPaperFixtures.length,
    }),
  ),
  http.post(`${api}/projects`, async ({ request }) => {
    const body = (await request.json()) as {
      title: string;
      description: string | null;
    };
    return HttpResponse.json(
      { ...projectFixtures[0], ...body, id: crypto.randomUUID() },
      { status: 201 },
    );
  }),
  http.patch(`${api}/projects/:projectId`, async ({ request }) => {
    const body = (await request.json()) as {
      title?: string;
      description?: string | null;
    };
    return HttpResponse.json({ ...projectFixtures[0], ...body });
  }),
  http.delete(
    `${api}/projects/:projectId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post(
    `${api}/projects/:projectId/leave`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post(`${api}/projects/:projectId/papers`, () =>
    HttpResponse.json({ added_count: 1, existing_count: 0 }, { status: 201 }),
  ),
  http.delete(
    `${api}/projects/:projectId/papers/:documentId`,
    ({ request }) => {
      const confirmed = request.headers.has("X-Scholens-Confirmation-Token");
      return confirmed
        ? new HttpResponse(null, { status: 204 })
        : HttpResponse.json(
            {
              code: "confirmation_required",
              details: {
                comment_count: 5,
                confirmation_token:
                  "test-confirmation-token-with-at-least-32-characters",
                thread_count: 2,
              },
              kind: "conflict",
              message: "Confirm annotation deletion",
              retryable: false,
            },
            { status: 409 },
          );
    },
  ),
];

export const projectHandlers = {
  populated,
  empty: [
    http.get(`${api}/projects`, () =>
      HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    ),
    ...populated,
  ],
  loading: [
    http.get(`${api}/projects`, async () => {
      await delay("infinite");
      return HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      });
    }),
    ...populated,
  ],
  error: [
    http.get(`${api}/projects`, () =>
      HttpResponse.json({ code: "unavailable" }, { status: 503 }),
    ),
    ...populated,
  ],
  papersEmpty: [
    http.get(`${api}/projects/:projectId/papers`, () =>
      HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    ),
    ...populated,
  ],
  outputsEmpty: [
    http.get(`${api}/projects/:projectId/outputs`, () =>
      HttpResponse.json({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    ),
    ...populated,
  ],
  noPaperManagement: [
    http.get(`${api}/projects/:projectId`, () =>
      HttpResponse.json({
        ...projectFixtures[0],
        capabilities: {
          ...projectFixtures[0]!.capabilities,
          manage_papers: false,
        },
        membership: {
          ...projectFixtures[0]!.membership,
          permissions: {
            ...projectFixtures[0]!.membership.permissions,
            manage_papers: false,
          },
        },
      }),
    ),
    ...populated,
  ],
  longTitle: [
    http.get(`${api}/projects/:projectId`, () =>
      HttpResponse.json({
        ...projectFixtures[0],
        title:
          "Longitudinal evidence synthesis for trustworthy retrieval systems across multilingual research contexts",
      }),
    ),
    ...populated,
  ],
};
