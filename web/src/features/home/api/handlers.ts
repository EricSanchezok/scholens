import { delay, http, HttpResponse } from "msw";

import {
  homeConversations,
  homePapers,
  homeProjects,
  homeTurns,
} from "./fixtures";

const api = "http://127.0.0.1:7301/api/v1";
const activeConversation = {
  ...homeConversations[0]!,
  paper_context: { kind: "library" as const },
  tool_permissions: [],
};

const baseHandlers = [
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({ items: homeConversations, next_cursor: null }),
  ),
  http.get(`${api}/library/papers`, () =>
    HttpResponse.json({
      items: homePapers,
      next_cursor: null,
      previous_cursor: null,
      total_count: homePapers.length,
    }),
  ),
  http.get(`${api}/projects`, () =>
    HttpResponse.json({ items: homeProjects, next_cursor: null }),
  ),
  http.get(`${api}/conversations/:conversationId`, () =>
    HttpResponse.json(activeConversation),
  ),
  http.get(`${api}/conversations/:conversationId/turns`, () =>
    HttpResponse.json({
      items: homeTurns,
      next_cursor: null,
      path_revision: 1,
    }),
  ),
  http.post(`${api}/conversations`, () =>
    HttpResponse.json(activeConversation, { status: 201 }),
  ),
  http.put(
    `${api}/conversations/:conversationId/context`,
    async ({ request }) => HttpResponse.json(await request.json()),
  ),
  http.post(
    `${api}/conversations/:conversationId/turns`,
    async ({ request }) => {
      const requestBody = (await request.json()) as {
        turn_id: string;
        response_id: string;
        user_query: string;
        locale: "en" | "zh-CN";
        time_zone: string;
        reasoning_level: string;
      };
      const finalizedResponse = {
        id: requestBody.response_id,
        variant_index: 1,
        status: "completed" as const,
        content: "The answer is grounded in your selected research.",
        references: null,
        artifacts: null,
        trace: {
          entries: [
            {
              kind: "activity" as const,
              id: "search-1",
              sequence: 1,
              category: "search" as const,
              state: "succeeded" as const,
              subject: "selected research",
              source_count: 1,
              artifact_count: 0,
            },
          ],
          citation_summary: {
            source_count: 1,
            annotation_count: 1,
            rejected_source_count: 0,
          },
        },
      };
      const finalizedTurn = {
        branch: { count: 1, index: 1 },
        depth: homeTurns.length + 1,
        id: requestBody.turn_id,
        user_query: requestBody.user_query,
        locale: requestBody.locale,
        time_zone: requestBody.time_zone,
        reasoning_level: requestBody.reasoning_level,
        paper_context: activeConversation.paper_context,
        parent_turn_id: homeTurns.at(-1)?.id ?? null,
        contexts: [],
        selected_response_id: requestBody.response_id,
        suggestions: null,
        responses: [finalizedResponse],
      };
      const events = [
        {
          type: "start",
          conversation_id: activeConversation.id,
          turn_id: requestBody.turn_id,
          response_id: requestBody.response_id,
          generation_kind: "initial",
          variant_index: 1,
        },
        {
          type: "activity",
          response_id: requestBody.response_id,
          activity: {
            kind: "activity",
            id: "search-1",
            sequence: 1,
            category: "search",
            state: "running",
            subject: "selected research",
          },
        },
        {
          type: "assistant_item_start",
          response_id: requestBody.response_id,
          item_id: `assistant:${requestBody.turn_id}:2`,
          sequence: 2,
        },
        {
          type: "assistant_item_delta",
          response_id: requestBody.response_id,
          item_id: `assistant:${requestBody.turn_id}:2`,
          delta: "The answer is grounded in your selected research.",
        },
        {
          type: "assistant_item_complete",
          response_id: requestBody.response_id,
          item: {
            id: `assistant:${requestBody.turn_id}:2`,
            sequence: 2,
            phase: "final",
            content: "The answer is grounded in your selected research.",
          },
        },
        { type: "response_ready", turn: finalizedTurn },
        {
          type: "suggestions",
          turn_id: requestBody.turn_id,
          response_id: requestBody.response_id,
          suggestions: [
            "Compare this with another paper.",
            "Show the supporting evidence.",
            "What should I investigate next?",
          ],
        },
        {
          type: "complete",
          turn_id: requestBody.turn_id,
          response_id: requestBody.response_id,
        },
      ];
      const body = events
        .map(
          (event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
        )
        .join("");
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    },
  ),
  http.post(
    `${api}/conversations/:conversationId/turns/:turnId/responses`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as { response_id: string };
      const turnId = String(params.turnId);
      const sourceTurn = homeTurns[0]!;
      const finalizedResponse = {
        id: requestBody.response_id,
        variant_index: sourceTurn.responses.length + 1,
        status: "completed" as const,
        content: "A regenerated answer grounded in the same turn.",
        references: null,
        artifacts: null,
        trace: null,
      };
      const finalizedTurn = {
        ...sourceTurn,
        id: turnId,
        selected_response_id: requestBody.response_id,
        responses: [...sourceTurn.responses, finalizedResponse],
      };
      const events = [
        {
          type: "start",
          conversation_id: activeConversation.id,
          turn_id: turnId,
          response_id: requestBody.response_id,
          generation_kind: "retry",
          variant_index: finalizedResponse.variant_index,
        },
        {
          type: "assistant_item_start",
          response_id: requestBody.response_id,
          item_id: `assistant:${turnId}:retry`,
          sequence: 1,
        },
        {
          type: "assistant_item_delta",
          response_id: requestBody.response_id,
          item_id: `assistant:${turnId}:retry`,
          delta: "A regenerated answer grounded in the same turn.",
        },
        {
          type: "assistant_item_complete",
          response_id: requestBody.response_id,
          item: {
            id: `assistant:${turnId}:retry`,
            sequence: 1,
            phase: "final",
            content: "A regenerated answer grounded in the same turn.",
          },
        },
        { type: "response_ready", turn: finalizedTurn },
        {
          type: "complete",
          turn_id: turnId,
          response_id: requestBody.response_id,
        },
      ];
      const body = events
        .map(
          (event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
        )
        .join("");
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    },
  ),
  http.put(
    `${api}/conversations/:conversationId/turns/:turnId/selected-response`,
    async ({ request }) => {
      const requestBody = (await request.json()) as { response_id: string };
      return HttpResponse.json({
        selected_response_id: requestBody.response_id,
      });
    },
  ),
];

export const homeHandlers = {
  populated: baseHandlers,
  empty: [
    http.get(`${api}/conversations`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`${api}/projects`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    ...baseHandlers,
  ],
  error: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    http.get(`${api}/projects`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    ...baseHandlers,
  ],
  slow: [
    http.get(`${api}/library/papers`, async () => {
      await delay(1_800);
      return HttpResponse.json({ items: homePapers, next_cursor: null });
    }),
    http.get(`${api}/projects`, async () => {
      await delay(1_800);
      return HttpResponse.json({ items: homeProjects, next_cursor: null });
    }),
    ...baseHandlers,
  ],
  readOnly: [
    http.get(`${api}/conversations/:conversationId`, () =>
      HttpResponse.json({
        ...activeConversation,
        read_only: true,
        read_only_reason: "scope_access_lost",
        capabilities: { ...activeConversation.capabilities, send: false },
      }),
    ),
    ...baseHandlers,
  ],
  processing: [
    http.post(
      `${api}/conversations/:conversationId/turns`,
      async ({ request }) => {
        const requestBody = (await request.json()) as {
          turn_id: string;
          response_id: string;
        };
        const encoder = new TextEncoder();
        const body = new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                [
                  {
                    type: "start",
                    conversation_id: activeConversation.id,
                    turn_id: requestBody.turn_id,
                    response_id: requestBody.response_id,
                    generation_kind: "initial",
                    variant_index: 1,
                  },
                  {
                    type: "activity",
                    response_id: requestBody.response_id,
                    activity: {
                      kind: "activity",
                      id: "search-1",
                      sequence: 1,
                      category: "search",
                      state: "running",
                      subject: "selected papers",
                    },
                  },
                ]
                  .map(
                    (event) =>
                      `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
                  )
                  .join(""),
              ),
            );
          },
        });
        return new HttpResponse(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      },
    ),
    ...baseHandlers,
  ],
  creationUnavailable: [
    http.post(`${api}/conversations/:conversationId/turns`, () =>
      HttpResponse.json(
        {
          code: "rate_limit_unavailable",
          message: "AI capacity checks are temporarily unavailable",
          retryable: true,
        },
        { status: 503 },
      ),
    ),
    ...baseHandlers,
  ],
};
