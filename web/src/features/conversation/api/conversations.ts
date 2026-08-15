import type { components } from "@/lib/api/generated/schema";
import {
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
  error: true,
} satisfies Record<ConversationStreamEvent["type"], true>;

export async function createConversation(body: ConversationCreateRequest) {
  const { data } = await apiClient.POST("/api/v1/conversations", { body });
  if (!data) throw new Error("Create conversation response was empty");
  return data;
}

export async function setConversationPinned(
  conversationId: string,
  pinned: boolean,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/conversations/{conversation_id}",
    {
      params: { path: { conversation_id: conversationId } },
      body: { pinned },
    },
  );
  if (!data) throw new Error("Update conversation response was empty");
  return data;
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
}: {
  path: string;
  body:
    | ConversationTurnCreateRequest
    | ConversationTurnBranchCreateRequest
    | ConversationResponseCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}${path}`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!response.ok) throw await toApiError(response);
  let completed = false;
  await consumeServerSentEvents({
    response,
    onEvent: (message) => {
      if (completed) return;
      const event = parseConversationEventData(message.data);
      onEvent(event);
      if (event.type === "complete" || event.type === "error") {
        completed = true;
      }
    },
  });
  if (!completed) {
    throw new Error("Conversation stream ended unexpectedly");
  }
}

export function streamConversationTurn({
  conversationId,
  request,
  signal,
  onEvent,
}: {
  conversationId: string;
  request: ConversationTurnCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  return streamConversation({
    path: `/api/v1/conversations/${conversationId}/turns`,
    body: request,
    signal,
    onEvent,
  });
}

export function streamConversationRetry({
  conversationId,
  turnId,
  request,
  signal,
  onEvent,
}: {
  conversationId: string;
  turnId: string;
  request: ConversationResponseCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  return streamConversation({
    path: `/api/v1/conversations/${conversationId}/turns/${turnId}/responses`,
    body: request,
    signal,
    onEvent,
  });
}

export function streamConversationBranch({
  conversationId,
  turnId,
  request,
  signal,
  onEvent,
}: {
  conversationId: string;
  turnId: string;
  request: ConversationTurnBranchCreateRequest;
  signal: AbortSignal;
  onEvent: (event: ConversationStreamEvent) => void;
}) {
  return streamConversation({
    path: `/api/v1/conversations/${conversationId}/turns/${turnId}/branches`,
    body: request,
    signal,
    onEvent,
  });
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
