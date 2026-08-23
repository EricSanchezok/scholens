import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelConversationGeneration,
  parseConversationEventBlock,
  streamConversationTurn,
  subscribeConversationEvents,
} from "./conversations";

const conversationId = "40000000-0000-4000-8000-000000000001";
const turnId = "50000000-0000-4000-8000-000000000001";
const responseId = "60000000-0000-4000-8000-000000000001";

function streamResponse(body: string) {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("conversation SSE parsing", () => {
  it("parses a typed standard SSE event", () => {
    expect(
      parseConversationEventBlock(
        'event: assistant_item_delta\ndata: {"type":"assistant_item_delta","item_id":"assistant-1","delta":"hello"}',
      ),
    ).toEqual({
      type: "assistant_item_delta",
      item_id: "assistant-1",
      delta: "hello",
    });
  });

  it("parses capability-gated assistant candidate events", () => {
    expect(
      parseConversationEventBlock(
        'event: assistant_candidate_delta\ndata: {"type":"assistant_candidate_delta","response_id":"60000000-0000-4000-8000-000000000001","item_id":"assistant-1","delta":"hello"}',
      ),
    ).toEqual({
      type: "assistant_candidate_delta",
      response_id: responseId,
      item_id: "assistant-1",
      delta: "hello",
    });
  });

  it("joins multiline data fields and ignores comments", () => {
    expect(
      parseConversationEventBlock(
        ': keep-alive\nevent: activity\ndata: {"type":"activity",\ndata: "activity":{"kind":"activity","id":"search-1","sequence":1,"category":"search","state":"running"}}',
      ),
    ).toEqual({
      type: "activity",
      activity: {
        kind: "activity",
        id: "search-1",
        sequence: 1,
        category: "search",
        state: "running",
      },
    });
  });

  it("ignores blocks without data", () => {
    expect(parseConversationEventBlock(": keep-alive")).toBeUndefined();
  });

  it("accepts the response-ready sidecar event sequence", () => {
    expect(
      parseConversationEventBlock(
        'event: suggestions\ndata: {"type":"suggestions","turn_id":"50000000-0000-4000-8000-000000000001","response_id":"60000000-0000-4000-8000-000000000001","suggestions":["One","Two","Three"]}',
      ),
    ).toEqual({
      type: "suggestions",
      turn_id: "50000000-0000-4000-8000-000000000001",
      response_id: "60000000-0000-4000-8000-000000000001",
      suggestions: ["One", "Two", "Three"],
    });
  });

  it("rejects event discriminators outside the generated contract", () => {
    expect(() =>
      parseConversationEventBlock(
        'data: {"type":"content_delta","delta":"legacy"}',
      ),
    ).toThrow("Conversation stream event was malformed");
  });
});

describe("durable conversation generation", () => {
  it("requests asynchronous acceptance and follows the detachable event stream", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          {
            conversation_id: conversationId,
            turn_id: turnId,
            response_id: responseId,
            variant_index: 1,
            generation_kind: "initial",
          },
          { status: 202 },
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          `id: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];
    const accepted: boolean[] = [];

    await streamConversationTurn({
      conversationId,
      request: {
        turn_id: turnId,
        response_id: responseId,
        user_query: "Question",
        locale: "en",
        time_zone: "Asia/Shanghai",
        reasoning_level: "standard",
        contexts: [],
      },
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
      onAccepted: (durable) => accepted.push(durable),
    });

    expect(accepted).toEqual([true]);
    expect(events).toEqual(["start", "complete"]);
    const post = fetchMock.mock.calls[0]?.[0] as Request;
    expect(post.headers.get("Prefer")).toBe("respond-async");
    expect(post.headers.get("Accept")).toContain("application/json");
    const subscription = fetchMock.mock.calls[1]?.[0] as Request;
    expect(subscription.method).toBe("GET");
    expect(subscription.url).toContain(`/${responseId}/events`);
    expect(subscription.headers.get("X-Scholens-Stream-Capabilities")).toBe(
      "assistant-candidates-v1",
    );
  });

  it("keeps the legacy inline SSE contract as a compatibility fallback", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `event: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const accepted: boolean[] = [];
    const events: string[] = [];

    await streamConversationTurn({
      conversationId,
      request: {
        turn_id: turnId,
        response_id: responseId,
        user_query: "Question",
        locale: "en",
        time_zone: "Asia/Shanghai",
        reasoning_level: "standard",
        contexts: [],
      },
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
      onAccepted: (durable) => accepted.push(durable),
    });

    expect(accepted).toEqual([false]);
    expect(events).toEqual(["start", "complete"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reconnects from the last durable event without replaying it", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\n`,
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          `id: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "setTimeout").mockImplementation(((
      handler: TimerHandler,
    ) => {
      queueMicrotask(() => {
        if (typeof handler === "function") handler();
      });
      return 1;
    }) as typeof window.setTimeout);
    const events: string[] = [];
    const states: string[] = [];

    await subscribeConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
      onConnectionState: (state) => states.push(state),
    });

    expect(events).toEqual(["start", "complete"]);
    expect(states).toEqual(["connected", "reconnecting", "connected"]);
    const resumed = fetchMock.mock.calls[1]?.[0] as Request;
    expect(resumed.headers.get("Last-Event-ID")).toBe("1-0");
  });

  it("surfaces malformed durable events instead of reconnecting forever", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(streamResponse('data: {"type":"unknown"}\n\n'));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      subscribeConversationEvents({
        conversationId,
        turnId,
        responseId,
        signal: new AbortController().signal,
        onEvent: () => undefined,
      }),
    ).rejects.toThrow("Conversation stream event was malformed");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses an explicit server cancellation instead of aborting generation locally", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({
        conversation_id: conversationId,
        turn_id: turnId,
        response_id: responseId,
        status: "cancelled",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await cancelConversationGeneration({
      conversationId,
      turnId,
      responseId,
    });

    expect(result.status).toBe("cancelled");
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toContain(`/${responseId}/cancel`);
  });
});
