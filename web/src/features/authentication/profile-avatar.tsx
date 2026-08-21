"use client";

import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Avatar, type AvatarProps, type AvatarSource } from "@/components/ui";
import { ApiError, apiClient } from "@/lib/api";
import { nextAvatarRefreshInterval } from "@/lib/query/avatar-refresh";
import { useAuthSession } from "./auth-session";

const RECOVERY_COOLDOWN_MS = 10 * 1_000;

export const profileAvatarKey = (userId: number | undefined) =>
  ["identity", "profile-avatar", userId] as const;

export const profileAvatarQuery = (userId: number | undefined) =>
  queryOptions({
    queryKey: profileAvatarKey(userId),
    queryFn: async ({ signal }) => {
      try {
        const { data } = await apiClient.GET("/api/v1/me/avatar", { signal });
        if (!data) throw new Error("Profile avatar response was empty");
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    refetchInterval: (query) => nextAvatarRefreshInterval([query.state.data]),
    staleTime: 10 * 60 * 1_000,
  });

export function CurrentUserAvatar(
  props: Omit<AvatarProps, "onImageError" | "source">,
) {
  const { actor, status } = useAuthSession();
  const queryClient = useQueryClient();
  const query = useQuery({
    ...profileAvatarQuery(actor?.id),
    enabled: status === "authenticated" && actor !== null,
  });
  const lastRecovery = React.useRef<
    { at: number; version: string } | undefined
  >(undefined);

  const recover = React.useCallback(
    (source: AvatarSource) => {
      const now = Date.now();
      if (
        lastRecovery.current?.version === source.version &&
        now - lastRecovery.current.at < RECOVERY_COOLDOWN_MS
      ) {
        return;
      }
      lastRecovery.current = { at: now, version: source.version };
      void queryClient.invalidateQueries({
        queryKey: profileAvatarKey(actor?.id),
      });
    },
    [actor?.id, queryClient],
  );

  return <Avatar {...props} onImageError={recover} source={query.data} />;
}
