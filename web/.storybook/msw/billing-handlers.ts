import { delay, http, HttpResponse } from "msw";

import type { components } from "@/lib/api/generated/schema";

const api = "http://127.0.0.1:7301/api/v1";
type CapacityResponse = components["schemas"]["CapacityResponse"];

export const researcherUsageFixture = {
  limits: {
    knowledge_base_size_kb: 3 * 1024 * 1024,
    paper_uploads: 500,
    projects: 100,
  },
  plan: "researcher",
  usage: {
    knowledge_base_size_kb: 768 * 1024,
    knowledge_base_size_remaining_kb: 2_304 * 1024,
    paper_uploads: 184,
    paper_uploads_remaining: 316,
    projects: 12,
    projects_remaining: 88,
  },
} satisfies CapacityResponse;

export const billingHandlers = {
  success: [
    http.get(`${api}/billing/capacity`, () =>
      HttpResponse.json(researcherUsageFixture),
    ),
  ],
  loading: [
    http.get(`${api}/billing/capacity`, async () => {
      await delay("infinite");
      return HttpResponse.json(researcherUsageFixture);
    }),
  ],
  unavailable: [
    http.get(`${api}/billing/capacity`, () =>
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
