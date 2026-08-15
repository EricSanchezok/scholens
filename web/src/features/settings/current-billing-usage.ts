"use client";

import { useQuery } from "@tanstack/react-query";

import { settingsQueries } from "./api";
import { addDaysToDateOnly } from "./formatters";

export type CurrentBillingUsageSummary =
  | { status: "loading" }
  | { retry: () => void; status: "error" }
  | {
      resetDate: string;
      plan: string;
      status: "success";
      tokenCreditsLimit: number;
      tokenCreditsUsed: number;
    };

export function useCurrentBillingUsage(): CurrentBillingUsageSummary {
  const usage = useQuery({
    ...settingsQueries.usage("current_week"),
    // The compact menu must surface an honest failure promptly; its explicit
    // Retry item is the recovery path.
    retry: false,
  });

  if (usage.isPending) return { status: "loading" };
  if (usage.isError) {
    return { retry: () => void usage.refetch(), status: "error" };
  }
  return {
    resetDate: addDaysToDateOnly(usage.data.period_end, 1),
    plan: usage.data.plan,
    status: "success",
    tokenCreditsLimit: usage.data.usage.token_credits_limit,
    tokenCreditsUsed: usage.data.usage.token_credits_used,
  };
}
