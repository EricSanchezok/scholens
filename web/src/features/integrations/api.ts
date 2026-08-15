import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

export type Integration =
  components["schemas"]["IntegrationConnectionResponse"];
export type IntegrationProvider = components["schemas"]["IntegrationProvider"];

export const integrationKeys = {
  all: ["integrations"] as const,
  current: () => ["integrations", "current"] as const,
};

export const integrationQueries = {
  current: () =>
    queryOptions({
      queryKey: integrationKeys.current(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/me/integrations", {
          signal,
        });
        if (!data) throw new Error("Integration response was empty");
        return data;
      },
    }),
};

export async function connectIntegration(
  provider: IntegrationProvider,
  credential: string,
) {
  const { data } = await apiClient.PUT("/api/v1/me/integrations/{provider}", {
    body: { credential },
    params: { path: { provider } },
  });
  if (!data) throw new Error("Integration response was empty");
  return data;
}

export async function setIntegrationEnabled(
  provider: IntegrationProvider,
  enabled: boolean,
) {
  const { data } = await apiClient.PATCH("/api/v1/me/integrations/{provider}", {
    body: { enabled },
    params: { path: { provider } },
  });
  if (!data) throw new Error("Integration response was empty");
  return data;
}

export async function disconnectIntegration(provider: IntegrationProvider) {
  await apiClient.DELETE("/api/v1/me/integrations/{provider}", {
    params: { path: { provider } },
  });
}
