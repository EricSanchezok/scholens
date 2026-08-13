import { queryOptions } from "@tanstack/react-query";

import {
  apiClient,
  authenticatedFetch,
  consumeServerSentEvents,
  toApiError,
  type ServerSentEvent,
} from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { clientEnvironment } from "@/lib/env/client";

export type TranslationPreferences =
  components["schemas"]["TranslationPreferencesResponse"];
export type TranslationPreferencesUpdate =
  components["schemas"]["TranslationPreferencesUpdateRequest"];

export type SelectionTranslationEvent =
  | {
      type: "start";
      cacheHit: boolean;
      targetLanguage: string;
    }
  | { type: "delta"; text: string }
  | { type: "complete"; cacheHit: boolean }
  | {
      type: "error";
      code: string;
      message: string;
      retryable: boolean;
    };

export const translationKeys = {
  all: ["reader", "translation"] as const,
  preferences: () => ["reader", "translation", "preferences"] as const,
};

export const translationQueries = {
  preferences: () =>
    queryOptions({
      queryKey: translationKeys.preferences(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/me/translation-preferences",
          { signal },
        );
        if (!data)
          throw new Error("Translation preferences response was empty");
        return data;
      },
      staleTime: 60_000,
    }),
};

export async function updateTranslationPreferences(
  body: TranslationPreferencesUpdate,
) {
  const { data } = await apiClient.PUT("/api/v1/me/translation-preferences", {
    body,
  });
  if (!data) throw new Error("Translation preferences response was empty");
  return data;
}

function readRecord(data: string) {
  const value: unknown = JSON.parse(data);
  if (!value || typeof value !== "object") {
    throw new Error("Translation stream event was malformed");
  }
  return value as Record<string, unknown>;
}

export function parseSelectionTranslationEvent(
  message: ServerSentEvent,
): SelectionTranslationEvent {
  const data = readRecord(message.data);
  switch (message.event) {
    case "start":
      if (
        typeof data.cache_hit !== "boolean" ||
        typeof data.target_language !== "string"
      ) {
        break;
      }
      return {
        type: "start",
        cacheHit: data.cache_hit,
        targetLanguage: data.target_language,
      };
    case "delta":
      if (typeof data.text !== "string") break;
      return { type: "delta", text: data.text };
    case "complete":
      if (typeof data.cache_hit !== "boolean") break;
      return { type: "complete", cacheHit: data.cache_hit };
    case "error":
      if (
        typeof data.code !== "string" ||
        typeof data.message !== "string" ||
        typeof data.retryable !== "boolean"
      ) {
        break;
      }
      return {
        type: "error",
        code: data.code,
        message: data.message,
        retryable: data.retryable,
      };
  }
  throw new Error("Translation stream event was malformed");
}

export async function streamSelectionTranslation({
  documentId,
  text,
  signal,
  onEvent,
}: {
  documentId: string;
  text: string;
  signal: AbortSignal;
  onEvent: (event: SelectionTranslationEvent) => void;
}) {
  const response = await authenticatedFetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/papers/${documentId}/selection-translations`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text }),
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
      if (event.type === "complete" || event.type === "error") {
        completed = true;
      }
    },
  });
  if (!completed) throw new Error("Translation stream ended unexpectedly");
}
