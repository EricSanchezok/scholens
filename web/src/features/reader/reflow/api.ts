import { queryOptions } from "@tanstack/react-query";

import {
  apiClient,
  authenticatedFetch,
  consumeServerSentEvents,
  toApiError,
} from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { clientEnvironment } from "@/lib/env/client";
import {
  parseSelectionTranslationEvent,
  type SelectionTranslationEvent,
} from "../translation/api";
export type { SelectionTranslationEvent } from "../translation/api";

export type DocumentReflow = components["schemas"]["DocumentReflowResponse"];
export type DocumentReflowBlock =
  components["schemas"]["DocumentReflowBlockResponse"];

export const reflowKeys = {
  all: ["reader", "reflow"] as const,
  document: (documentId: string) =>
    ["reader", "reflow", "document", documentId] as const,
};

export const reflowQueries = {
  document: (documentId: string, enabled: boolean) =>
    queryOptions({
      enabled,
      queryKey: reflowKeys.document(documentId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/reflow",
          {
            params: { path: { document_id: documentId } },
            signal,
          },
        );
        if (!data) throw new Error("Document reflow response was empty");
        return data;
      },
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status === "pending" || status === "processing" ? 1_500 : false;
      },
      retry: false,
    }),
};

export async function retryDocumentReflow(documentId: string) {
  const { data } = await apiClient.POST(
    "/api/v1/papers/{document_id}/reflow/retries",
    { params: { path: { document_id: documentId } } },
  );
  if (!data) throw new Error("Document reflow retry response was empty");
  return data;
}

export async function streamReflowBlockTranslation({
  blockId,
  documentId,
  onEvent,
  signal,
}: {
  blockId: string;
  documentId: string;
  onEvent: (event: SelectionTranslationEvent) => void;
  signal: AbortSignal;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/papers/${encodeURIComponent(documentId)}/reflow/blocks/${encodeURIComponent(blockId)}/translations`,
    {
      credentials: "include",
      headers: { Accept: "text/event-stream" },
      method: "POST",
      signal,
    },
  );
  if (!response.ok) throw await toApiError(response);

  let completed = false;
  await consumeServerSentEvents({
    response,
    onEvent: (message) => {
      if (completed) return;
      const event = parseSelectionTranslationEvent(message);
      onEvent(event);
      if (event.type === "complete" || event.type === "error") completed = true;
    },
  });
  if (!completed) throw new Error("Translation stream ended unexpectedly");
}
