import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

export type AccessKey = components["schemas"]["AccessKeyResponse"];
export type AccessKeyCreate = components["schemas"]["AccessKeyCreateRequest"];
export type UsagePeriod = "current_week" | "four_weeks" | "twelve_weeks";

export const settingsKeys = {
  all: ["settings"] as const,
  profile: () => ["settings", "profile"] as const,
  usage: (period: UsagePeriod) => ["settings", "usage", period] as const,
  accessKeys: () => ["settings", "access-keys"] as const,
};

export const settingsQueries = {
  profile: () =>
    queryOptions({
      queryKey: settingsKeys.profile(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/me/profile", { signal });
        if (!data) throw new Error("Profile response was empty");
        return data;
      },
    }),
  usage: (period: UsagePeriod) =>
    queryOptions({
      queryKey: settingsKeys.usage(period),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/billing/usage", {
          params: { query: { period } },
          signal,
        });
        if (!data) throw new Error("Usage response was empty");
        return data;
      },
    }),
  accessKeys: () =>
    queryOptions({
      queryKey: settingsKeys.accessKeys(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/me/access-keys", {
          params: { query: { limit: 100 } },
          signal,
        });
        if (!data) throw new Error("Access key response was empty");
        return data;
      },
    }),
};

export async function updateProfile(displayName: string) {
  const { data } = await apiClient.PATCH("/api/v1/me/profile", {
    body: { display_name: displayName },
  });
  if (!data) throw new Error("Profile response was empty");
  return data;
}

export async function changePassword(body: {
  current_password: string;
  new_password: string;
}) {
  await apiClient.POST("/api/v1/auth/change-password", { body });
}

export async function createAccessKey(body: AccessKeyCreate) {
  const { data } = await apiClient.POST("/api/v1/me/access-keys", { body });
  if (!data) throw new Error("Access key response was empty");
  return data;
}

export async function updateAccessKey(
  accessKeyId: string,
  body: components["schemas"]["AccessKeyUpdateRequest"],
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/me/access-keys/{access_key_id}",
    { body, params: { path: { access_key_id: accessKeyId } } },
  );
  if (!data) throw new Error("Access key response was empty");
  return data;
}

export async function revokeAccessKey(accessKeyId: string) {
  await apiClient.DELETE("/api/v1/me/access-keys/{access_key_id}", {
    params: { path: { access_key_id: accessKeyId } },
  });
}
