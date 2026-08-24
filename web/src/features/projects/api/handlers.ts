import { delay, http, HttpResponse } from "msw";

import {
  projectConversationFixtures,
  projectFixtures,
  projectLibraryPaperFixtures,
  projectInvitationFixtures,
  projectMemberFixtures,
  projectOutputFixtures,
  projectPaperFixtures,
} from "./fixtures";

const api = "http://127.0.0.1:7301/api/v1";

const populated = [
  http.post(
    `${api}/me/reading-activity/paper-summaries`,
    async ({ request }) => {
      const body = (await request.json()) as { document_ids: string[] };
      return HttpResponse.json({
        items: body.document_ids.slice(0, 100).map((documentId, index) => ({
          active_ms: (index + 1) * 18 * 60_000,
          coverage_percent: 32 + index * 14,
          document_id: documentId,
          page_buckets: Array.from({ length: 8 }, (_, bucket) => ({
            active_ms: bucket % 3 === 0 ? 0 : (index + bucket + 1) * 15_000,
            end_page: (bucket + 1) * 3,
            start_page: bucket * 3 + 1,
          })),
          visible_ms: (index + 1) * 24 * 60_000,
        })),
      });
    },
  ),
  http.get(`${api}/projects/:projectId/insights`, ({ params, request }) => {
    const range = new URL(request.url).searchParams.get("range") ?? "30d";
    return HttpResponse.json({
      activity_history_complete_since: "2026-07-01T00:00:00Z",
      metric_definition_version: "active-reading-v1",
      mine: {
        annotation_count: 7,
        papers_with_activity: 2,
        private_conversation_count: 4,
        reading: {
          active_days: 8,
          active_ms: 5_940_000,
          coverage_percent: 54,
          session_count: 12,
          substantive_pages: 19,
          visible_ms: 7_020_000,
        },
      },
      papers: projectPaperFixtures.map((paper, index) => ({
        document_id: paper.document_id,
        last_activity_at: `2026-08-${22 + index}T08:00:00Z`,
        my_active_ms: (index + 2) * 31 * 60_000,
        my_coverage_percent: 42 + index * 19,
        discussion_message_count: index + 2,
        shared_annotation_count: index + 1,
        title: paper.title,
      })),
      papers_total_count: projectPaperFixtures.length,
      project_id: params.projectId,
      range,
      reading_data_since: "2026-07-01T00:00:00Z",
      team: {
        active_collaborators: 2,
        active_ms: null,
        anonymous_reading_available: false,
        outputs: 2,
        papers_added: 2,
        papers_with_activity: null,
        resolved_discussions: 1,
        shared_annotations: 9,
        discussion_message_count: 12,
        substantive_pages: null,
        visible_ms: null,
      },
      time_zone: "UTC",
      trend: Array.from({ length: 30 }, (_, index) => ({
        date: new Date(Date.UTC(2026, 6, 26 + index))
          .toISOString()
          .slice(0, 10),
        my_active_ms: index % 5 === 0 ? 0 : (18 + index * 2) * 60_000,
        shared_activity_count: index % 4,
        team_active_ms: null,
      })),
    });
  }),
  http.get(`${api}/projects/:projectId/activity`, ({ params }) =>
    HttpResponse.json({
      items: [
        {
          actor_display_name: "Mina Park",
          document_id: projectPaperFixtures[0]!.document_id,
          document_title: projectPaperFixtures[0]!.title,
          id: "annotation:story",
          kind: "annotation_created",
          occurred_at: "2026-08-24T08:00:00Z",
        },
      ],
      next_cursor: null,
      project_id: params.projectId,
    }),
  ),
  http.delete(
    `${api}/projects/:projectId/me/reading-activity`,
    () => new HttpResponse(null, { status: 204 }),
  ),
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
  http.get(`${api}/projects/:projectId/members`, () =>
    HttpResponse.json({ items: projectMemberFixtures, next_cursor: null }),
  ),
  http.get(`${api}/projects/:projectId/invitations`, () =>
    HttpResponse.json({ items: projectInvitationFixtures, next_cursor: null }),
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
  http.post(`${api}/projects/:projectId/invitations`, async ({ request }) => {
    const body = (await request.json()) as {
      email: string;
      edit_project: boolean;
      manage_collaborators: boolean;
      manage_papers: boolean;
    };
    return HttpResponse.json(
      {
        ...projectInvitationFixtures[0],
        ...body,
        id: crypto.randomUUID(),
        permissions: {
          edit_project: body.edit_project,
          manage_collaborators: body.manage_collaborators,
          manage_papers: body.manage_papers,
        },
      },
      { status: 201 },
    );
  }),
  http.post(
    `${api}/projects/:projectId/invitations/:invitationId/resend`,
    ({ params }) =>
      HttpResponse.json({
        ...projectInvitationFixtures[0],
        id: params.invitationId,
      }),
  ),
  http.delete(
    `${api}/projects/:projectId/invitations/:invitationId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.patch(
    `${api}/projects/:projectId/members/:userId`,
    async ({ params, request }) => {
      const permissions = await request.json();
      return HttpResponse.json({
        ...projectMemberFixtures[1],
        permissions,
        user_id: Number(params.userId),
      });
    },
  ),
  http.delete(
    `${api}/projects/:projectId/members/:userId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post(`${api}/project-invitations/:token/accept`, () =>
    HttpResponse.json({ project_id: projectFixtures[0]!.id }),
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
