import { delay, http, HttpResponse } from "msw";

import type { components } from "@/lib/api/generated/schema";

const api = "http://127.0.0.1:7301/api/v1";
type UsageResponse = components["schemas"]["UsageResponse"];

export const researcherUsageFixture = {
  limits: {
    knowledge_base_size_kb: 3 * 1024 * 1024,
    paper_uploads: 500,
    project_papers: 120,
    projects: 100,
    token_credits_weekly: 100_000_000,
  },
  period: "current_week",
  period_end: "2026-08-16",
  period_start: "2026-08-10",
  plan: "researcher",
  usage: {
    knowledge_base_size_kb: 768 * 1024,
    knowledge_base_size_remaining_kb: 2_304 * 1024,
    paper_uploads: 184,
    paper_uploads_remaining: 316,
    projects: 12,
    projects_remaining: 88,
    token_credits_limit: 100_000_000,
    token_credits_overage: 0,
    token_credits_remaining: 76_000_000,
    token_credits_used: 24_000_000,
  },
} satisfies UsageResponse;

function usageForRequest(request: Request): UsageResponse {
  const period =
    (new URL(request.url).searchParams.get("period") as
      UsageResponse["period"] | null) ?? "current_week";
  const weeks =
    period === "twelve_weeks" ? 12 : period === "four_weeks" ? 4 : 1;
  return {
    ...researcherUsageFixture,
    period,
    period_start: weeks === 1 ? "2026-08-10" : "2026-07-20",
    usage: {
      ...researcherUsageFixture.usage,
      token_credits_limit:
        researcherUsageFixture.usage.token_credits_limit * weeks,
      token_credits_remaining:
        researcherUsageFixture.usage.token_credits_remaining * weeks,
      token_credits_used:
        researcherUsageFixture.usage.token_credits_used * weeks,
    },
  };
}

export const billingHandlers = {
  success: [
    http.get(`${api}/billing/usage`, ({ request }) =>
      HttpResponse.json(usageForRequest(request)),
    ),
  ],
  loading: [
    http.get(`${api}/billing/usage`, async () => {
      await delay("infinite");
      return HttpResponse.json(researcherUsageFixture);
    }),
  ],
  unavailable: [
    http.get(`${api}/billing/usage`, () =>
      HttpResponse.json(
        {
          code: "billing_usage_unavailable",
          kind: "unavailable",
          message: "Billing usage is temporarily unavailable",
          retryable: true,
        },
        { status: 503 },
      ),
    ),
  ],
};
