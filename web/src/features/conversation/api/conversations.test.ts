import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelConversationGeneration,
  parseConversationEventBlock,
  streamConversationStart,
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

function turnRequest() {
  return {
    turn_id: turnId,
    response_id: responseId,
    user_query: "Question",
    locale: "en" as const,
    time_zone: "Asia/Shanghai",
    reasoning_level: "standard" as const,
    contexts: [],
  };
}

afterEach(() => {
  vi.useRealTimers();
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

  it("normalizes a research-agent style v2 envelope", () => {
    expect(
      parseConversationEventBlock(
        'id: 1710000000000-1\nevent: phase.updated\ndata: {"protocol_version":2,"event":"phase.updated","response_id":"60000000-0000-4000-8000-000000000001","seq":1,"emitted_at":"2026-09-02T00:00:00Z","data":{"phase":"tool","elapsed_ms":1200}}',
      ),
    ).toEqual({
      type: "phase",
      response_id: responseId,
      phase: "tool",
      elapsed_ms: 1200,
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
    expect(() =>
      parseConversationEventBlock('data: {"type":"toString"}'),
    ).toThrow("Conversation stream event was malformed");
  });

  it("rejects a known terminal event without its immutable identity", () => {
    expect(() =>
      parseConversationEventBlock('data: {"type":"complete"}'),
    ).toThrow("Conversation stream event was malformed");
  });
});

describe("durable conversation generation", () => {
  it("uses the direct durable stream by default", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `: accepted\n\nid: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nid: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];
    const accepted: string[] = [];

    await streamConversationTurn({
      conversationId,
      request: turnRequest(),
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
      onAccepted: (streamKind) => accepted.push(streamKind),
    });

    expect(accepted).toEqual(["direct"]);
    expect(events).toEqual(["start", "complete"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const post = fetchMock.mock.calls[0]?.[0] as Request;
    expect(post.method).toBe("POST");
    expect(post.url).not.toContain("include_candidates");
    expect(post.headers.get("Prefer")).toBeNull();
    expect(post.headers.get("Accept")).toBe(
      "text/event-stream, application/json",
    );
    expect(post.signal.aborted).toBe(false);
  });

  it("supports a 202 compatibility response and follows the durable stream", async () => {
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
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nid: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];
    const accepted: string[] = [];

    await streamConversationTurn({
      conversationId,
      request: turnRequest(),
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
      onAccepted: (streamKind) => accepted.push(streamKind),
    });

    expect(accepted).toEqual(["resume"]);
    expect(events).toEqual(["start", "complete"]);
    const post = fetchMock.mock.calls[0]?.[0] as Request;
    expect(post.headers.get("Prefer")).toBeNull();
    expect(post.headers.get("Accept")).toContain("application/json");
    const subscription = fetchMock.mock.calls[1]?.[0] as Request;
    expect(subscription.method).toBe("GET");
    expect(subscription.url).toContain(`/api/v2/conversations/`);
    expect(subscription.url).toContain(`/${responseId}/events`);
  });

  it("atomically creates a conversation and starts its first turn", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nid: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await streamConversationStart({
      conversationId,
      request: {
        conversation: {
          scope_type: "global",
          paper_context: { kind: "library" },
        },
        turn: turnRequest(),
      },
      signal: new AbortController().signal,
      onEvent: () => undefined,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toContain(`/conversations/${conversationId}/start`);
    expect(await request.json()).toEqual({
      conversation: {
        scope_type: "global",
        paper_context: { kind: "library" },
      },
      turn: turnRequest(),
    });
  });

  it("resumes a direct stream from its last durable event", async () => {
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
    const events: string[] = [];

    await streamConversationTurn({
      conversationId,
      request: turnRequest(),
      signal: new AbortController().signal,
      onEvent: (event) => events.push(event.type),
    });

    expect(events).toEqual(["start", "complete"]);
    const resumed = fetchMock.mock.calls[1]?.[0] as Request;
    expect(resumed.method).toBe("GET");
    expect(resumed.headers.get("Last-Event-ID")).toBe("1-0");
  });

  it("retries an ambiguous acceptance with the same idempotent request", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nid: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const streaming = streamConversationTurn({
      conversationId,
      request: turnRequest(),
      signal: new AbortController().signal,
      onEvent: () => undefined,
    });
    await vi.advanceTimersByTimeAsync(500);
    await streaming;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const requests = fetchMock.mock.calls.map((call) => call[0] as Request);
    expect(await requests[0]?.clone().json()).toEqual(
      await requests[1]?.clone().json(),
    );
  });

  it("bounds header acceptance and retries with a fresh signal", async () => {
    vi.useFakeTimers();
    const requestSignals: AbortSignal[] = [];
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementationOnce((input) => {
        const request = input as Request;
        requestSignals.push(request.signal);
        return new Promise<Response>((_resolve, reject) => {
          request.signal.addEventListener(
            "abort",
            () => reject(request.signal.reason),
            { once: true },
          );
        });
      })
      .mockImplementationOnce(async (input) => {
        requestSignals.push((input as Request).signal);
        return streamResponse(
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\nid: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        );
      });
    vi.stubGlobal("fetch", fetchMock);

    const streaming = streamConversationTurn({
      conversationId,
      request: turnRequest(),
      signal: new AbortController().signal,
      onEvent: () => undefined,
    });
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(500);
    await streaming;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestSignals).toHaveLength(2);
    expect(requestSignals[0]?.aborted).toBe(true);
    expect(requestSignals[1]).not.toBe(requestSignals[0]);
    expect(requestSignals[1]?.aborted).toBe(false);
    const requests = fetchMock.mock.calls.map((call) => call[0] as Request);
    expect(await requests[0]?.clone().json()).toEqual(
      await requests[1]?.clone().json(),
    );
  });

  it("does not reconnect when the event consumer throws a TypeError", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: start\ndata: {"type":"start","conversation_id":"${conversationId}","turn_id":"${turnId}","response_id":"${responseId}","variant_index":1,"generation_kind":"initial"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      streamConversationTurn({
        conversationId,
        request: turnRequest(),
        signal: new AbortController().signal,
        onEvent: () => {
          throw new TypeError("consumer bug");
        },
      }),
    ).rejects.toThrow("consumer bug");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.signal.aborted).toBe(true);
  });

  it("deduplicates a replayed delta after reconnecting from its cursor", async () => {
    const firstDelta = `{"type":"assistant_candidate_delta","response_id":"${responseId}","item_id":"assistant-1","delta":"Hello "}`;
    const secondDelta = `{"type":"assistant_candidate_delta","response_id":"${responseId}","item_id":"assistant-1","delta":"world"}`;
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: assistant_candidate_delta\ndata: ${firstDelta}\n\n`,
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          `id: 1-0\nevent: assistant_candidate_delta\ndata: ${firstDelta}\n\nid: 2-0\nevent: assistant_candidate_delta\ndata: ${secondDelta}\n\nid: 3-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
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
    const deltas: string[] = [];
    const states: string[] = [];

    await subscribeConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal: new AbortController().signal,
      onEvent: (event) => {
        if (event.type === "assistant_candidate_delta") {
          deltas.push(event.delta);
        }
      },
      onConnectionState: (state) => states.push(state),
    });

    expect(deltas).toEqual(["Hello ", "world"]);
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
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.signal.aborted).toBe(true);
  });

  it("treats authorization failures as terminal", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ detail: "forbidden" }, { status: 403 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      subscribeConversationEvents({
        conversationId,
        turnId,
        responseId,
        signal: new AbortController().signal,
        onEvent: () => undefined,
      }),
    ).rejects.toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reconnects when an open stream receives no bytes for 40 seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementationOnce(async (input) => {
        const request = input as Request;
        return new Response(
          new ReadableStream({
            start(controller) {
              request.signal.addEventListener(
                "abort",
                () => controller.error(request.signal.reason),
                { once: true },
              );
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      })
      .mockResolvedValueOnce(
        streamResponse(
          `id: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const states: string[] = [];

    const subscription = subscribeConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal: new AbortController().signal,
      onEvent: () => undefined,
      onConnectionState: (state) => states.push(state),
    });
    await vi.advanceTimersByTimeAsync(40_000);
    await vi.advanceTimersByTimeAsync(500);
    await subscription;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(states).toEqual(["connected", "reconnecting", "connected"]);
  });

  it("reconnects when an event subscription receives no headers", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    let firstSignal: AbortSignal | undefined;
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementationOnce((input) => {
        firstSignal = (input as Request).signal;
        return new Promise<Response>((_resolve, reject) => {
          firstSignal?.addEventListener(
            "abort",
            () => reject(firstSignal?.reason),
            { once: true },
          );
        });
      })
      .mockResolvedValueOnce(
        streamResponse(
          `id: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const subscription = subscribeConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal: new AbortController().signal,
      onEvent: () => undefined,
    });
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(500);
    await subscription;

    expect(firstSignal?.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("waits offline and reconnects immediately on the online event", async () => {
    let online = false;
    vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        streamResponse(
          `id: 2-0\nevent: complete\ndata: {"type":"complete","turn_id":"${turnId}","response_id":"${responseId}"}\n\n`,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const states: string[] = [];

    const subscription = subscribeConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal: new AbortController().signal,
      onEvent: () => undefined,
      onConnectionState: (state) => states.push(state),
    });
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    online = true;
    window.dispatchEvent(new window.Event("online"));
    await subscription;

    expect(states).toEqual(["offline", "connected"]);
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
