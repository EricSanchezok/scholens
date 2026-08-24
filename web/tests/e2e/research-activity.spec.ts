import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { mockBillingUsage } from "./billing-fixture";

const apiPattern = "**/api/v1";
const actor = {
  id: 7,
  email: "eric@scholens.ai",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Eric",
  locale: "en",
};

function researchInsights(range: string, timeZone: string) {
  return {
    activity_history_complete_since: "2026-01-01T00:00:00Z",
    annotation_count: 12,
    conversation_count: 4,
    metric_definition_version: "active-reading-v1",
    output_count: 3,
    papers_with_activity: 5,
    projects: [
      {
        active_ms: 7_200_000,
        project_id: "50000000-0000-4000-8000-000000000001",
        session_count: 8,
        title: "Living World Engine",
      },
    ],
    range,
    reading_data_since: "2026-08-01T00:00:00Z",
    summary: {
      active_days: 7,
      active_ms: 12_600_000,
      coverage_percent: range === "all" ? 42 : null,
      session_count: 12,
      substantive_pages: range === "all" ? 16 : null,
      visible_ms: 15_300_000,
    },
    time_zone: timeZone,
    top_papers: [
      {
        active_ms: 4_500_000,
        document_id: "10000000-0000-4000-8000-000000000001",
        last_read_at: "2026-08-24T08:00:00Z",
        session_count: 5,
        title: "Generative Agents",
      },
    ],
    trend: [
      {
        active_ms: 1_800_000,
        date: "2026-08-23",
        session_count: 2,
        visible_ms: 2_100_000,
      },
      {
        active_ms: 2_400_000,
        date: "2026-08-24",
        session_count: 3,
        visible_ms: 2_900_000,
      },
    ],
  };
}

async function mockResearchActivity(page: Page) {
  await mockBillingUsage(page);
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      body: JSON.stringify({
        access_token: "playwright-access",
        actor,
        token_type: "bearer",
      }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      body: JSON.stringify({ items: [], next_cursor: null }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/me/reading-activity-preferences`, (route) =>
    route.fulfill({
      body: JSON.stringify({
        contribute_anonymous_project_aggregates: true,
        recording_enabled: true,
      }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/me/research-insights**`, (route) => {
    const url = new URL(route.request().url());
    return route.fulfill({
      body: JSON.stringify(
        researchInsights(
          url.searchParams.get("range") ?? "365d",
          url.searchParams.get("time_zone") ?? "UTC",
        ),
      ),
      contentType: "application/json",
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockResearchActivity(page);
});

test("shows populated research activity, changes range, and stays accessible on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/me/activity");

  await expect(
    page.getByRole("heading", { level: 1, name: "Research activity" }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Activity range" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "1 year" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.getByText("Active reading estimate", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Living World Engine" }),
  ).toBeVisible();

  const nextInsights = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname === "/api/v1/me/research-insights" &&
      url.searchParams.get("range") === "90d"
    );
  });
  await page.getByRole("button", { name: "90 days" }).click();
  await nextInsights;
  await expect(page).toHaveURL(/\/me\/activity\?range=90d$/);
  await expect(page.getByRole("button", { name: "90 days" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  // App Router metadata can stream after the client surface becomes visible.
  // Wait for the accessible document title before running the full-page audit.
  await expect(page).toHaveTitle("Scholens");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});
