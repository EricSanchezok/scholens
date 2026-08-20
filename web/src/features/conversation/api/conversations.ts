import type { components } from "@/lib/api/generated/schema";
import {
  ApiError,
  apiClient,
  authenticatedFetch,
  consumeServerSentEvents,
  parseServerSentEventBlock,
  toApiError,
} from "@/lib/api";
import { clientEnvironment } from "@/lib/env/client";

export type ConversationStreamEvent =
  components["schemas"]["ConversationStreamEventSchema"];
export type ConversationTurnCreateRequest =
  components["schemas"]["ConversationTurnCreateRequest"];
export type ConversationTurnBranchCreateRequest =
  components["schemas"]["ConversationTurnBranchCreateRequest"];
export type ConversationResponseCreateRequest =
  components["schemas"]["ConversationResponseCreateRequest"];
export type ConversationCreateRequest =
  components["schemas"]["ConversationCreateRequest"];
export type ConversationUpdateRequest =
  components["schemas"]["ConversationUpdateRequest"];
export type ConversationGenerationAccepted =
  components["schemas"]["ConversationGenerationAccepted"];

const conversationStreamEventTypes = {
  start: true,
  activity: true,
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

export async function createConversation(body: ConversationCreateRequest) {
  const { data } = await apiClient.POST("/api/v1/conversations", { body });
  if (!data) throw new Error("Create conversation response was empty");
  return data;
}

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
    !(value.type in conversationStreamEventTypes)
  ) {
    throw new Error("Conversation stream event was malformed");
  }
  return value as ConversationStreamEvent;
}

async function streamConversation({
  path,
  body,
  signal,
  onEvent,
  onAccepted,
  onConnectionState,
}: {
  path: string;
  body:
    | ConversationTurnCreateRequest
    | ConversationTurnBranchCreateRequest
    | ConversationResponseCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
  onAccepted?: (durable: boolean) => void;
  onConnectionState?: (state: "connected" | "reconnecting") => void;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}${path}`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json, text/event-stream",
        "Content-Type": "application/json",
        Prefer: "respond-async",
      },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!response.ok) throw await toApiError(response);
  if (response.status === 202) {
    const accepted = (await response.json()) as ConversationGenerationAccepted;
    const expectedTurnId =
      "turn_id" in body ? body.turn_id : path.split("/")[6];
    if (
      accepted.conversation_id !== path.split("/")[4] ||
      accepted.turn_id !== expectedTurnId ||
      accepted.response_id !== body.response_id
    ) {
      throw new Error("Conversation acceptance response was malformed");
    }
    onAccepted?.(true);
    onEvent({
      type: "start",
      conversation_id: accepted.conversation_id,
      turn_id: accepted.turn_id,
      response_id: accepted.response_id,
      variant_index: accepted.variant_index,
      generation_kind: accepted.generation_kind,
    });
    await subscribeConversationEvents({
      conversationId: accepted.conversation_id,
      turnId: accepted.turn_id,
      responseId: accepted.response_id,
      signal,
      onEvent,
      onConnectionState,
    });
    return;
  }
  onAccepted?.(false);
  let completed = false;
  await consumeServerSentEvents({
    response,
    onEvent: (message) => {
      if (completed) return;
      const event = parseConversationEventData(message.data);
      onEvent(event);
      if (
        event.type === "complete" ||
        event.type === "cancelled" ||
        event.type === "error"
      ) {
        completed = true;
      }
    },
  });
  if (!completed) {
    throw new Error("Conversation stream ended unexpectedly");
  }
}

function waitForReconnect(signal: AbortSignal, delayMs: number) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timeout);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timeout = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function isReconnectableSubscriptionError(error: unknown) {
  return (
    (error instanceof ApiError && error.status >= 500) ||
    error instanceof TypeError ||
    (error instanceof DOMException && error.name === "NetworkError")
  );
}

export async function subscribeConversationEvents({
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
  onConnectionState?: (state: "connected" | "reconnecting") => void;
}) {
  let lastEventId: string | undefined;
  let reconnectDelayMs = 500;
  const seenEventIds = new Set<string>();
  while (!signal.aborted) {
    try {
      const response = await authenticatedFetch(
        `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/conversations/${conversationId}/turns/${turnId}/responses/${responseId}/events`,
        {
          method: "GET",
          credentials: "include",
          headers: {
            Accept: "text/event-stream",
            ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
          },
          signal,
        },
      );
      if (!response.ok) throw await toApiError(response);
      onConnectionState?.("connected");
      reconnectDelayMs = 500;
      let terminal = false;
      await consumeServerSentEvents({
        response,
        onEvent: (message) => {
          if (message.id) {
            lastEventId = message.id;
            if (seenEventIds.has(message.id)) return;
            seenEventIds.add(message.id);
          }
          const event = parseConversationEventData(message.data);
          onEvent(event);
          terminal = ["complete", "cancelled", "error"].includes(event.type);
        },
      });
      if (terminal) return;
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (!isReconnectableSubscriptionError(error)) throw error;
    }
    onConnectionState?.("reconnecting");
    await waitForReconnect(signal, reconnectDelayMs);
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 5_000);
  }
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
  onAccepted?: (durable: boolean) => void;
  onConnectionState?: (state: "connected" | "reconnecting") => void;
}) {
  return streamConversation({
    path: `/api/v1/conversations/${conversationId}/turns`,
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
  onAccepted?: (durable: boolean) => void;
  onConnectionState?: (state: "connected" | "reconnecting") => void;
}) {
  return streamConversation({
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
  onAccepted?: (durable: boolean) => void;
  onConnectionState?: (state: "connected" | "reconnecting") => void;
}) {
  return streamConversation({
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
