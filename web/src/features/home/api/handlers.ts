import { delay, http, HttpResponse } from "msw";

import type { components } from "@/lib/api/generated/schema";
import {
  homeConversations,
  homePapers,
  homeProjects,
  homeTurns,
} from "./fixtures";

type ConversationTurn = components["schemas"]["ConversationTurnResponse"];
type StartRequest = components["schemas"]["ConversationStartRequest"];
type TurnRequest = components["schemas"]["ConversationTurnCreateRequest"];

const api = "http://127.0.0.1:7301/api/v1";
const apiV2 = "http://127.0.0.1:7301/api/v2";
const activeConversation = {
  ...homeConversations[0]!,
  paper_context: { kind: "library" as const },
  tool_permissions: [],
};
const persistedTurns = new Map<string, ConversationTurn[]>();

export function resetHomeHandlerState() {
  persistedTurns.clear();
}

function eventStream(events: Array<Record<string, unknown>>) {
  const body = events
    .map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
  return new HttpResponse(body, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

const v2EventNames: Record<string, string> = {
  start: "turn.started",
  activity: "message.part.updated",
  assistant_item_start: "message.part.updated",
  assistant_item_delta: "message.part.delta",
  assistant_item_complete: "message.part.completed",
  response_ready: "response.ready",
  suggestions: "suggestions.ready",
  complete: "turn.completed",
  cancelled: "turn.canceled",
  error: "turn.failed",
};

function v2EventStream(
  events: Array<Record<string, unknown>>,
  responseId: string,
) {
  const body = events
    .map((event, index) => {
      const type = String(event.type);
      const data = { ...event };
      delete data.type;
      delete data.response_id;
      if (type === "activity") {
        data.part_id = (event.activity as Record<string, unknown>).id;
        data.part_kind = "activity";
        data.version = index + 1;
        data.state = (event.activity as Record<string, unknown>).state;
        data.presentation = event.activity;
        delete data.activity;
      } else if (type === "assistant_item_start") {
        data.part_id = event.item_id;
        data.part_kind = "progress";
        data.version = index + 1;
        data.state = "running";
        delete data.item_id;
      } else if (type === "assistant_item_delta") {
        data.part_id = event.item_id;
        data.part_kind = "progress";
        data.version = index + 1;
        delete data.item_id;
      } else if (type === "assistant_item_complete") {
        const item = event.item as Record<string, unknown>;
        data.part_id = item.id;
        data.part_kind = item.phase === "final" ? "final" : "progress";
        data.version = index + 1;
        data.state = "completed";
        data.snapshot = item;
        delete data.item;
      }
      const envelope = {
        protocol_version: 2,
        event: v2EventNames[type] ?? type,
        response_id: responseId,
        seq: index + 1,
        emitted_at: "2026-09-02T00:00:00.000Z",
        data,
      };
      return `id: ${Date.now()}-${index}\nevent: ${envelope.event}\ndata: ${JSON.stringify(envelope)}\n\n`;
    })
    .join("");
  return new HttpResponse(body, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function completedTurnStream(
  conversationId: string,
  request: TurnRequest,
  paperContext: ConversationTurn["paper_context"] = activeConversation.paper_context,
  resetConversation = false,
  protocol: "v1" | "v2" = "v1",
) {
  const previousTurns = resetConversation
    ? []
    : (persistedTurns.get(conversationId) ??
      (conversationId === activeConversation.id ? homeTurns : []));
  const finalizedResponse = {
    id: request.response_id,
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
        status: "complete" as const,
        grounding_status: "not_evaluated" as const,
        available_source_count: 1,
        unlinked_source_count: 0,
        dropped_annotation_count: 0,
        unverified_claim_count: 0,
      },
    },
  };
  const finalizedTurn = {
    branch: { count: 1, index: 1 },
    depth: previousTurns.length + 1,
    id: request.turn_id,
    user_query: request.user_query,
    locale: request.locale,
    time_zone: request.time_zone,
    reasoning_level: request.reasoning_level,
    paper_context: paperContext,
    parent_turn_id: previousTurns.at(-1)?.id ?? null,
    contexts: [],
    selected_response_id: request.response_id,
    suggestions: null,
    responses: [finalizedResponse],
  } satisfies ConversationTurn;
  persistedTurns.set(conversationId, [...previousTurns, finalizedTurn]);
  const events = [
    {
      type: "start",
      conversation_id: conversationId,
      turn_id: request.turn_id,
      response_id: request.response_id,
      generation_kind: "initial",
      variant_index: 1,
    },
    {
      type: "activity",
      response_id: request.response_id,
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
      response_id: request.response_id,
      item_id: `assistant:${request.turn_id}:2`,
      sequence: 2,
    },
    {
      type: "assistant_item_delta",
      response_id: request.response_id,
      item_id: `assistant:${request.turn_id}:2`,
      delta: "The answer is grounded in your selected research.",
    },
    {
      type: "assistant_item_complete",
      response_id: request.response_id,
      item: {
        id: `assistant:${request.turn_id}:2`,
        sequence: 2,
        phase: "final",
        content: "The answer is grounded in your selected research.",
      },
    },
    { type: "response_ready", turn: finalizedTurn },
    {
      type: "suggestions",
      turn_id: request.turn_id,
      response_id: request.response_id,
      suggestions: [
        "Compare this with another paper.",
        "Show the supporting evidence.",
        "What should I investigate next?",
      ],
    },
    {
      type: "complete",
      turn_id: request.turn_id,
      response_id: request.response_id,
    },
  ];
  return protocol === "v2"
    ? v2EventStream(events, request.response_id)
    : eventStream(events);
}

function processingStream(
  conversationId: string,
  request: TurnRequest,
  protocol: "v1" | "v2" = "v1",
) {
  const events = [
    {
      type: "start",
      conversation_id: conversationId,
      turn_id: request.turn_id,
      response_id: request.response_id,
      generation_kind: "initial",
      variant_index: 1,
    },
    {
      type: "activity",
      response_id: request.response_id,
      activity: {
        kind: "activity",
        id: "search-1",
        sequence: 1,
        category: "search",
        state: "running",
        subject: "selected papers",
      },
    },
  ];
  if (protocol === "v2") return v2EventStream(events, request.response_id);
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          events
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
}

const baseHandlers = [
  http.get(`${api}/me/research-insights`, () =>
    HttpResponse.json({
      activity_history_complete_since: "2026-07-01T00:00:00Z",
      annotation_count: 12,
      conversation_count: 7,
      metric_definition_version: "active-reading-v1",
      output_count: 3,
      papers_with_activity: 9,
      projects: [
        {
          active_ms: 5_040_000,
          project_id: homeProjects[0]!.id,
          session_count: 8,
          title: homeProjects[0]!.title,
        },
      ],
      range: "30d",
      reading_data_since: "2026-07-01T00:00:00Z",
      summary: {
        active_days: 12,
        active_ms: 8_460_000,
        coverage_percent: 62,
        session_count: 21,
        substantive_pages: 37,
        visible_ms: 10_020_000,
      },
      time_zone: "UTC",
      top_papers: [
        {
          active_ms: 2_460_000,
          document_id: homePapers[0]!.document.document_id,
          last_read_at: "2026-08-23T08:00:00Z",
          session_count: 5,
          title: homePapers[0]!.document.title,
        },
      ],
      trend: Array.from({ length: 30 }, (_, index) => ({
        active_ms: index % 5 === 0 ? 0 : (20 + index * 3) * 60_000,
        date: new Date(Date.UTC(2026, 6, 26 + index))
          .toISOString()
          .slice(0, 10),
        session_count: index % 5 === 0 ? 0 : 1,
        visible_ms: index % 5 === 0 ? 0 : (25 + index * 3) * 60_000,
      })),
    }),
  ),
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
  http.get(`${api}/conversations/:conversationId`, ({ params }) =>
    HttpResponse.json({
      ...activeConversation,
      id: String(params.conversationId),
    }),
  ),
  http.get(`${api}/conversations/:conversationId/turns`, ({ params }) =>
    HttpResponse.json({
      items:
        persistedTurns.get(String(params.conversationId)) ??
        (params.conversationId === activeConversation.id ? homeTurns : []),
      next_cursor: null,
      path_revision: 1,
    }),
  ),
  http.post(
    `${api}/conversations/:conversationId/start`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as StartRequest;
      return completedTurnStream(
        String(params.conversationId),
        requestBody.turn,
        requestBody.conversation.paper_context ??
          activeConversation.paper_context,
        true,
      );
    },
  ),
  http.post(
    `${apiV2}/conversations/:conversationId/start`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as StartRequest;
      return completedTurnStream(
        String(params.conversationId),
        requestBody.turn,
        requestBody.conversation.paper_context ??
          activeConversation.paper_context,
        true,
        "v2",
      );
    },
  ),
  http.put(
    `${api}/conversations/:conversationId/context`,
    async ({ request }) => HttpResponse.json(await request.json()),
  ),
  http.post(
    `${api}/conversations/:conversationId/turns`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as TurnRequest;
      return completedTurnStream(String(params.conversationId), requestBody);
    },
  ),
  http.post(
    `${apiV2}/conversations/:conversationId/turns`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as TurnRequest;
      return completedTurnStream(
        String(params.conversationId),
        requestBody,
        activeConversation.paper_context,
        false,
        "v2",
      );
    },
  ),
  http.get(
    `${apiV2}/conversations/:conversationId/turns/:turnId/responses/:responseId/events`,
    ({ params }) =>
      v2EventStream(
        [
          {
            type: "complete",
            turn_id: String(params.turnId),
            response_id: String(params.responseId),
          },
        ],
        String(params.responseId),
      ),
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
  http.post(
    `${apiV2}/conversations/:conversationId/turns/:turnId/responses`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as { response_id: string };
      const sourceTurn = homeTurns[0]!;
      const turnRequest: TurnRequest = {
        turn_id: String(params.turnId),
        response_id: requestBody.response_id,
        user_query: sourceTurn.user_query,
        locale: sourceTurn.locale,
        time_zone: sourceTurn.time_zone,
        contexts: sourceTurn.contexts,
        reasoning_level:
          sourceTurn.reasoning_level as TurnRequest["reasoning_level"],
      };
      return completedTurnStream(
        String(params.conversationId),
        turnRequest,
        sourceTurn.paper_context,
        false,
        "v2",
      );
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
  http.post(
    `${apiV2}/conversations/:conversationId/turns/:turnId/branches`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as TurnRequest;
      return completedTurnStream(
        String(params.conversationId),
        requestBody,
        activeConversation.paper_context,
        false,
        "v2",
      );
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
      `${api}/conversations/:conversationId/start`,
      async ({ request, params }) => {
        const requestBody = (await request.json()) as StartRequest;
        return processingStream(
          String(params.conversationId),
          requestBody.turn,
        );
      },
    ),
    http.post(
      `${apiV2}/conversations/:conversationId/start`,
      async ({ request, params }) => {
        const requestBody = (await request.json()) as StartRequest;
        return processingStream(
          String(params.conversationId),
          requestBody.turn,
          "v2",
        );
      },
    ),
    ...baseHandlers,
  ],
  creationUnavailable: [
    http.post(`${api}/conversations/:conversationId/start`, () =>
      HttpResponse.json(
        {
          code: "rate_limit_unavailable",
          message: "AI capacity checks are temporarily unavailable",
          retryable: true,
        },
        { status: 503 },
      ),
    ),
    http.post(`${apiV2}/conversations/:conversationId/start`, () =>
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
