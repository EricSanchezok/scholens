import type { Page } from "@playwright/test";

const apiPattern = "**/api/v1";

export const billingUsageFixture = {
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
};

export async function mockBillingUsage(page: Page) {
  await page.route(`${apiPattern}/billing/usage**`, (route) =>
    route.fulfill({
      body: JSON.stringify(billingUsageFixture),
      contentType: "application/json",
    }),
  );
}
