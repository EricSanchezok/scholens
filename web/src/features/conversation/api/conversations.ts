import type { components } from "@/lib/api/generated/schema";
import {
  ApiError,
  apiClient,
  authenticatedFetch,
  parseServerSentEventBlock,
  toApiError,
} from "@/lib/api";
import { clientEnvironment } from "@/lib/env/client";

export type ConversationStreamEvent =
  components["schemas"]["ConversationCandidateSubscriptionEventSchema"];
export type ConversationTurnCreateRequest =
  components["schemas"]["ConversationTurnCreateRequest"];
export type ConversationTurnBranchCreateRequest =
  components["schemas"]["ConversationTurnBranchCreateRequest"];
export type ConversationResponseCreateRequest =
  components["schemas"]["ConversationResponseCreateRequest"];
export type ConversationStartRequest =
  components["schemas"]["ConversationStartRequest"];
export type ConversationUpdateRequest =
  components["schemas"]["ConversationUpdateRequest"];
export type ConversationGenerationAccepted =
  components["schemas"]["ConversationGenerationAccepted"];
export type ConversationConnectionState =
  "connected" | "offline" | "reconnecting";
export type ConversationStreamKind = "direct" | "resume";

type ConversationGenerationRequest =
  | ConversationStartRequest
  | ConversationTurnCreateRequest
  | ConversationTurnBranchCreateRequest
  | ConversationResponseCreateRequest;

type ConversationEventCursor = {
  lastEventId?: string;
  seenEventIds: Set<string>;
};

const ACCEPTANCE_TIMEOUT_MS = 10_000;
const CANDIDATE_STREAM_MEDIA_TYPE =
  "application/vnd.scholens.conversation-events";

const conversationStreamEventTypes = {
  start: true,
  activity: true,
  assistant_candidate_start: true,
  assistant_candidate_delta: true,
  assistant_candidate_reset: true,
  assistant_item_start: true,
  assistant_item_delta: true,
  assistant_item_complete: true,
  references: true,
  response_ready: true,
  suggestions: true,
  complete: true,
  cancelled: true,
  error: true,
} satisfies Record<ConversationStreamEvent["type"], true>;

export async function updateConversation(
  conversationId: string,
  body: ConversationUpdateRequest,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/conversations/{conversation_id}",
    {
      params: { path: { conversation_id: conversationId } },
      body,
    },
  );
  if (!data) throw new Error("Update conversation response was empty");
  return data;
}

export function setConversationPinned(conversationId: string, pinned: boolean) {
  return updateConversation(conversationId, { pinned });
}

export async function deleteConversation(conversationId: string) {
  await apiClient.DELETE("/api/v1/conversations/{conversation_id}", {
    params: { path: { conversation_id: conversationId } },
  });
}

export async function updateConversationContext(
  conversationId: string,
  context:
    | components["schemas"]["LibraryPaperContext"]
    | components["schemas"]["SelectedPaperContext"],
) {
  const { data } = await apiClient.PUT(
    "/api/v1/conversations/{conversation_id}/context",
    {
      params: { path: { conversation_id: conversationId } },
      body: context,
    },
  );
  if (!data) throw new Error("Update conversation context response was empty");
  return data;
}

export function parseConversationEventBlock(
  block: string,
): ConversationStreamEvent | undefined {
  const event = parseServerSentEventBlock(block);
  if (!event) return undefined;
  return parseConversationEventData(event.data);
}

function parseConversationEventData(data: string): ConversationStreamEvent {
  const value: unknown = JSON.parse(data);
  if (
    !value ||
    typeof value !== "object" ||
    !("type" in value) ||
    typeof value.type !== "string" ||
    !Object.hasOwn(conversationStreamEventTypes, value.type)
  ) {
    throw new Error("Conversation stream event was malformed");
  }
  if (!hasValidLifecycleShape(value)) {
    throw new Error("Conversation stream event was malformed");
  }
  return value as ConversationStreamEvent;
}

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function hasUuid(value: Record<string, unknown>, field: string) {
  return typeof value[field] === "string" && uuidPattern.test(value[field]);
}

function hasValidLifecycleShape(value: Record<string, unknown>) {
  switch (value.type) {
    case "start":
      return (
        hasUuid(value, "conversation_id") &&
        hasUuid(value, "turn_id") &&
        hasUuid(value, "response_id") &&
        Number.isInteger(value.variant_index) &&
        ["initial", "retry", "branch"].includes(String(value.generation_kind))
      );
    case "complete":
    case "cancelled":
      return hasUuid(value, "turn_id") && hasUuid(value, "response_id");
    case "error":
      return (
        hasUuid(value, "response_id") &&
        Boolean(value.error) &&
        typeof value.error === "object" &&
        !Array.isArray(value.error)
      );
    case "response_ready": {
      const turn = value.turn;
      return (
        Boolean(turn) &&
        typeof turn === "object" &&
        !Array.isArray(turn) &&
        hasUuid(turn as Record<string, unknown>, "id") &&
        Array.isArray((turn as Record<string, unknown>).responses)
      );
    }
    case "suggestions":
      return (
        hasUuid(value, "turn_id") &&
        hasUuid(value, "response_id") &&
        Array.isArray(value.suggestions) &&
        value.suggestions.length === 3 &&
        value.suggestions.every((suggestion) => typeof suggestion === "string")
      );
    default:
      return true;
  }
}

async function streamConversation({
  conversationId,
  turnId,
  responseId,
  path,
  body,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  conversationId: string;
  turnId: string;
  responseId: string;
  path: string;
  body: ConversationGenerationRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (streamKind: ConversationStreamKind) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  const cursor: ConversationEventCursor = { seenEventIds: new Set() };
  let directAccepted = false;
  let requestController: AbortController | undefined;
  let removeRequestAbortListener: () => void = () => undefined;
  try {
    let response: Response | undefined;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const attemptController = new AbortController();
      const abortAttempt = () => attemptController.abort(signal.reason);
      signal.addEventListener("abort", abortAttempt, { once: true });
      const acceptanceWatchdog = window.setTimeout(() => {
        attemptController.abort(new ConversationHeaderTimeout());
      }, ACCEPTANCE_TIMEOUT_MS);
      try {
        try {
          response = await authenticatedFetch(
            `${clientEnvironment.NEXT_PUBLIC_API_URL}${path}`,
            {
              method: "POST",
              credentials: "include",
              headers: {
                Accept: `${CANDIDATE_STREAM_MEDIA_TYPE}, text/event-stream, application/json`,
                "Content-Type": "application/json",
              },
              body: JSON.stringify(body),
              signal: attemptController.signal,
            },
          );
        } catch (error) {
          if (
            attemptController.signal.reason instanceof ConversationHeaderTimeout
          ) {
            throw attemptController.signal.reason;
          }
          throw asConversationTransportError(error);
        }
        if (!response.ok) throw await toApiError(response);
        requestController = attemptController;
        removeRequestAbortListener = () =>
          signal.removeEventListener("abort", abortAttempt);
        break;
      } catch (error) {
        if (signal.aborted) throw new DOMException("Aborted", "AbortError");
        if (attempt > 0 || !isReconnectableSubscriptionError(error)) {
          throw error;
        }
        onConnectionState?.(isBrowserOffline() ? "offline" : "reconnecting");
        await waitForReconnect(signal, 500);
      } finally {
        window.clearTimeout(acceptanceWatchdog);
        if (requestController !== attemptController) {
          signal.removeEventListener("abort", abortAttempt);
        }
      }
    }
    if (!response || !requestController) {
      throw new Error("Conversation request ended before receiving a response");
    }
    if (response.status === 202) {
      const bodyWatchdog = window.setTimeout(() => {
        requestController?.abort(new ConversationHeaderTimeout());
      }, ACCEPTANCE_TIMEOUT_MS);
      let accepted: ConversationGenerationAccepted;
      try {
        accepted = (await response.json()) as ConversationGenerationAccepted;
      } catch (error) {
        if (
          requestController.signal.reason instanceof ConversationHeaderTimeout
        ) {
          throw requestController.signal.reason;
        }
        throw asConversationTransportError(error);
      } finally {
        window.clearTimeout(bodyWatchdog);
        removeRequestAbortListener();
        removeRequestAbortListener = () => undefined;
      }
      if (
        accepted.conversation_id !== conversationId ||
        accepted.turn_id !== turnId ||
        accepted.response_id !== responseId
      ) {
        throw new Error("Conversation acceptance response was malformed");
      }
      onAccepted?.("resume");
      await followConversationEvents({
        conversationId,
        turnId,
        responseId,
        signal,
        cursor,
        onEvent,
        onConnectionState,
      });
      return;
    }

    directAccepted = true;
    onAccepted?.("direct");
    onConnectionState?.("connected");
    const terminal = await consumeConversationEventResponse({
      response,
      requestController,
      cursor,
      onEvent,
    });
    if (terminal) return;
    removeRequestAbortListener();
    removeRequestAbortListener = () => undefined;
    onConnectionState?.("reconnecting");
    await followConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal,
      cursor,
      onEvent,
      onConnectionState,
    });
  } catch (error) {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    if (!directAccepted || !isReconnectableSubscriptionError(error)) {
      throw error;
    }
    onConnectionState?.(isBrowserOffline() ? "offline" : "reconnecting");
    await followConversationEvents({
      conversationId,
      turnId,
      responseId,
      signal,
      cursor,
      onEvent,
      onConnectionState,
    });
  } finally {
    removeRequestAbortListener();
  }
}

function waitForReconnect(signal: AbortSignal, delayMs: number) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
      window.removeEventListener("online", onConnectivityChange);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      resolve();
    };
    const onAbort = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("online", onConnectivityChange);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const onConnectivityChange = () => finish();
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") finish();
    };
    const timeout = window.setTimeout(finish, delayMs);
    signal.addEventListener("abort", onAbort, { once: true });
    window.addEventListener("online", onConnectivityChange, { once: true });
    document.addEventListener("visibilitychange", onVisibilityChange);
  });
}

class ConversationNoBytesTimeout extends Error {
  constructor() {
    super("Conversation stream received no bytes for 40 seconds");
    this.name = "ConversationNoBytesTimeout";
  }
}

class ConversationHeaderTimeout extends Error {
  constructor() {
    super("Conversation server did not respond within 10 seconds");
    this.name = "ConversationHeaderTimeout";
  }
}

class ConversationTransportError extends Error {
  constructor(cause: unknown) {
    super("Conversation transport failed", { cause });
    this.name = "ConversationTransportError";
  }
}

function asConversationTransportError(error: unknown) {
  if (
    error instanceof TypeError ||
    (error instanceof DOMException && error.name === "NetworkError")
  ) {
    return new ConversationTransportError(error);
  }
  return error;
}

async function consumeConversationSubscription({
  response,
  requestController,
  onEvent,
}: {
  response: Response;
  requestController: AbortController;
  onEvent: (event: ReturnType<typeof parseServerSentEventBlock>) => void;
}) {
  if (!response.body) throw new Error("Event stream response was empty");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let watchdog: number | undefined;
  const armWatchdog = () => {
    if (watchdog !== undefined) window.clearTimeout(watchdog);
    watchdog = window.setTimeout(() => {
      requestController.abort(new ConversationNoBytesTimeout());
    }, 40_000);
  };
  armWatchdog();
  try {
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        if (
          requestController.signal.reason instanceof ConversationNoBytesTimeout
        ) {
          throw requestController.signal.reason;
        }
        throw asConversationTransportError(error);
      }
      const { done, value } = result;
      if (value?.byteLength) armWatchdog();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      blocks.forEach((block) => onEvent(parseServerSentEventBlock(block)));
      if (done) break;
    }
    onEvent(parseServerSentEventBlock(buffer));
  } catch (error) {
    if (requestController.signal.reason instanceof ConversationNoBytesTimeout) {
      throw requestController.signal.reason;
    }
    if (!requestController.signal.aborted) requestController.abort(error);
    throw error;
  } finally {
    if (watchdog !== undefined) window.clearTimeout(watchdog);
    reader.releaseLock();
  }
}

function consumeConversationMessage({
  message,
  cursor,
  onEvent,
}: {
  message: ReturnType<typeof parseServerSentEventBlock>;
  cursor: ConversationEventCursor;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  if (!message) return false;
  if (message.id) {
    cursor.lastEventId = message.id;
    if (cursor.seenEventIds.has(message.id)) return false;
    cursor.seenEventIds.add(message.id);
  }
  const event = parseConversationEventData(message.data);
  onEvent(event);
  return ["complete", "cancelled", "error"].includes(event.type);
}

async function consumeConversationEventResponse({
  response,
  requestController,
  cursor,
  onEvent,
}: {
  response: Response;
  requestController: AbortController;
  cursor: ConversationEventCursor;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  let terminal = false;
  await consumeConversationSubscription({
    response,
    requestController,
    onEvent: (message) => {
      if (terminal) return;
      terminal = consumeConversationMessage({ message, cursor, onEvent });
    },
  });
  return terminal;
}

function isReconnectableSubscriptionError(error: unknown) {
  return (
    (error instanceof ApiError && error.status >= 500) ||
    error instanceof ConversationHeaderTimeout ||
    error instanceof ConversationNoBytesTimeout ||
    error instanceof ConversationTransportError
  );
}

function isBrowserOffline() {
  return navigator.onLine === false;
}

async function followConversationEvents({
  conversationId,
  turnId,
  responseId,
  signal,
  cursor,
  onEvent,
  onConnectionState,
}: {
  conversationId: string;
  turnId: string;
  responseId: string;
  signal: AbortSignal;
  cursor: ConversationEventCursor;
  onEvent: (event: ConversationStreamEvent) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  let reconnectDelayMs = 500;
  while (!signal.aborted) {
    if (isBrowserOffline()) {
      onConnectionState?.("offline");
      await waitForReconnect(signal, 5_000);
      continue;
    }
    const requestController = new AbortController();
    const abortRequest = () => requestController.abort(signal.reason);
    signal.addEventListener("abort", abortRequest, { once: true });
    const headerWatchdog = window.setTimeout(() => {
      requestController.abort(new ConversationHeaderTimeout());
    }, ACCEPTANCE_TIMEOUT_MS);
    try {
      let response: Response;
      try {
        response = await authenticatedFetch(
          `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/conversations/${conversationId}/turns/${turnId}/responses/${responseId}/events/candidates`,
          {
            method: "GET",
            credentials: "include",
            headers: {
              Accept: "text/event-stream",
              ...(cursor.lastEventId
                ? { "Last-Event-ID": cursor.lastEventId }
                : {}),
            },
            signal: requestController.signal,
          },
        );
      } catch (error) {
        if (
          requestController.signal.reason instanceof ConversationHeaderTimeout
        ) {
          throw requestController.signal.reason;
        }
        throw asConversationTransportError(error);
      }
      window.clearTimeout(headerWatchdog);
      if (!response.ok) throw await toApiError(response);
      onConnectionState?.("connected");
      reconnectDelayMs = 500;
      const terminal = await consumeConversationEventResponse({
        response,
        requestController,
        cursor,
        onEvent,
      });
      if (terminal) return;
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (!isReconnectableSubscriptionError(error)) throw error;
    } finally {
      window.clearTimeout(headerWatchdog);
      signal.removeEventListener("abort", abortRequest);
    }
    onConnectionState?.(isBrowserOffline() ? "offline" : "reconnecting");
    const jitteredDelayMs = Math.min(
      5_000,
      reconnectDelayMs + Math.floor(Math.random() * reconnectDelayMs * 0.5),
    );
    await waitForReconnect(signal, jitteredDelayMs);
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 5_000);
  }
}

export function subscribeConversationEvents({
  conversationId,
  turnId,
  responseId,
  signal,
  onEvent,
  onConnectionState,
}: {
  conversationId: string;
  turnId: string;
  responseId: string;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  return followConversationEvents({
    conversationId,
    turnId,
    responseId,
    signal,
    cursor: { seenEventIds: new Set() },
    onEvent,
    onConnectionState,
  });
}

export function streamConversationTurn({
  conversationId,
  request,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  conversationId: string;
  request: ConversationTurnCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (streamKind: ConversationStreamKind) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  return streamConversation({
    conversationId,
    turnId: request.turn_id,
    responseId: request.response_id,
    path: `/api/v1/conversations/${conversationId}/turns`,
    body: request,
    signal,
    onEvent,
    onAccepted,
    onConnectionState,
  });
}

export function streamConversationStart({
  conversationId,
  request,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  conversationId: string;
  request: ConversationStartRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (streamKind: ConversationStreamKind) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  return streamConversation({
    conversationId,
    turnId: request.turn.turn_id,
    responseId: request.turn.response_id,
    path: `/api/v1/conversations/${conversationId}/start`,
    body: request,
    signal,
    onEvent,
    onAccepted,
    onConnectionState,
  });
}

export function streamConversationRetry({
  conversationId,
  turnId,
  request,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  conversationId: string;
  turnId: string;
  request: ConversationResponseCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (streamKind: ConversationStreamKind) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  return streamConversation({
    conversationId,
    turnId,
    responseId: request.response_id,
    path: `/api/v1/conversations/${conversationId}/turns/${turnId}/responses`,
    body: request,
    signal,
    onEvent,
    onAccepted,
    onConnectionState,
  });
}

export function streamConversationBranch({
  conversationId,
  turnId,
  request,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  conversationId: string;
  turnId: string;
  request: ConversationTurnBranchCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (streamKind: ConversationStreamKind) => void;
  onConnectionState?: (state: ConversationConnectionState) => void;
}) {
  return streamConversation({
    conversationId,
    turnId: request.turn_id,
    responseId: request.response_id,
    path: `/api/v1/conversations/${conversationId}/turns/${turnId}/branches`,
    body: request,
    signal,
    onEvent,
    onAccepted,
    onConnectionState,
  });
}

export async function cancelConversationGeneration({
  conversationId,
  turnId,
  responseId,
}: {
  conversationId: string;
  turnId: string;
  responseId: string;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/conversations/${conversationId}/turns/${turnId}/responses/${responseId}/cancel`,
    { method: "POST", credentials: "include" },
  );
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as components["schemas"]["ConversationGenerationCancellation"];
}

export async function selectConversationResponse({
  conversationId,
  turnId,
  responseId,
}: {
  conversationId: string;
  turnId: string;
  responseId: string;
}) {
  const { data } = await apiClient.PUT(
    "/api/v1/conversations/{conversation_id}/turns/{turn_id}/selected-response",
    {
      params: { path: { conversation_id: conversationId, turn_id: turnId } },
      body: { response_id: responseId },
    },
  );
  if (!data) throw new Error("Selected response was empty");
  return data;
}

export async function selectConversationBranch({
  conversationId,
  turnId,
}: {
  conversationId: string;
  turnId: string;
}) {
  const { data } = await apiClient.PUT(
    "/api/v1/conversations/{conversation_id}/selected-branch",
    {
      params: { path: { conversation_id: conversationId } },
      body: { turn_id: turnId },
    },
  );
  if (!data) throw new Error("Selected conversation branch was empty");
  return data;
}
