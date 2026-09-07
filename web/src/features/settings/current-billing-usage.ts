"use client";

import { useQuery } from "@tanstack/react-query";

import { settingsQueries } from "./api";

export type CurrentBillingUsageSummary =
  | { status: "loading" }
  | { retry: () => void; status: "error" }
  | {
      plan: string;
      status: "success";
      storageLimitKb: number;
      storageUsedKb: number;
    };

export function useCurrentBillingUsage(): CurrentBillingUsageSummary {
  const usage = useQuery({
    ...settingsQueries.usage(),
    // The compact menu must surface an honest failure promptly; its explicit
    // Retry item is the recovery path.
    retry: false,
  });

  if (usage.isPending) return { status: "loading" };
  if (usage.isError) {
    return { retry: () => void usage.refetch(), status: "error" };
  }
  return {
    plan: usage.data.plan,
    status: "success",
    storageLimitKb: usage.data.limits.knowledge_base_size_kb,
    storageUsedKb: usage.data.usage.knowledge_base_size_kb,
  };
}
