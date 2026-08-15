import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

export type TranslationPreferences =
  components["schemas"]["TranslationPreferencesResponse"];
export type TranslationPreferencesUpdate =
  components["schemas"]["TranslationPreferencesUpdateRequest"];

export const translationPreferenceKeys = {
  all: ["translation-preferences"] as const,
  current: () => ["translation-preferences", "current"] as const,
};

export const translationPreferenceQuery = () =>
  queryOptions({
    queryKey: translationPreferenceKeys.current(),
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.GET(
        "/api/v1/me/translation-preferences",
        { signal },
      );
      if (!data) throw new Error("Translation preferences response was empty");
      return data;
    },
    staleTime: 60_000,
  });

export async function updateTranslationPreferences(
  body: TranslationPreferencesUpdate,
) {
  const { data } = await apiClient.PUT("/api/v1/me/translation-preferences", {
    body,
  });
  if (!data) throw new Error("Translation preferences response was empty");
  return data;
}
