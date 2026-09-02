import { devices, expect, type Page, test } from "@playwright/test";

const apiPattern = "**/api/v*";

test.use({ ...devices["Pixel 7"] });

async function mockAnonymousSession(page: Page) {
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "auth_session_missing",
        kind: "unauthenticated",
        message: "session missing",
        retryable: false,
      }),
    }),
  );
}

async function mockWorkspace(page: Page) {
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "pwa-access",
        token_type: "bearer",
        actor: {
          id: 7,
          email: "eric@scholens.ai",
          email_verified: true,
          is_active: true,
          is_admin: false,
          is_blocked: false,
          status: "active",
          display_name: "Eric",
          locale: "en",
        },
      }),
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        next_cursor: null,
        previous_cursor: null,
        total_count: 0,
      }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/billing/usage**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        limits: {
          knowledge_base_size_kb: 5_242_880,
          paper_uploads: 300,
          project_papers: 300,
          projects: 10,
          token_credits_weekly: 30_000_000,
        },
        period: "current_week",
        period_end: "2026-08-23",
        period_start: "2026-08-17",
        plan: "basic",
        usage: {
          knowledge_base_size_kb: 0,
          knowledge_base_size_remaining_kb: 5_242_880,
          paper_uploads: 0,
          paper_uploads_remaining: 300,
          projects: 0,
          projects_remaining: 10,
          token_credits_limit: 30_000_000,
          token_credits_overage: 0,
          token_credits_remaining: 30_000_000,
          token_credits_used: 0,
        },
      }),
    }),
  );
}

test("publishes a standalone manifest with maskable artwork", async ({
  request,
}) => {
  const response = await request.get("/manifest.webmanifest");
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain(
    "application/manifest+json",
  );
  const manifest = (await response.json()) as {
    display: string;
    icons: Array<{ purpose?: string; sizes: string }>;
  };
  expect(manifest.display).toBe("standalone");
  expect(manifest.icons).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ purpose: "maskable", sizes: "512x512" }),
    ]),
  );
});

test("uses the Android installation event from the permanent mobile entry", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();

  await page.evaluate(() => {
    Object.assign(window, { __installPromptCalls: 0 });
    const event = new Event("beforeinstallprompt", { cancelable: true });
    Object.assign(event, {
      prompt: async () => {
        Object.assign(window, {
          __installPromptCalls:
            ((window as unknown as { __installPromptCalls: number })
              .__installPromptCalls ?? 0) + 1,
        });
      },
      userChoice: Promise.resolve({ outcome: "accepted" }),
    });
    window.dispatchEvent(event);
  });

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Install Scholens" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as unknown as { __installPromptCalls: number })
            .__installPromptCalls,
      ),
    )
    .toBe(1);
});

test("keeps controlled online navigation working before using the offline fallback", async ({
  context,
  page,
}) => {
  await mockAnonymousSession(page);
  await page.goto("/login");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (navigator.serviceWorker.controller) return;
    await new Promise<void>((resolve) => {
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => resolve(),
        {
          once: true,
        },
      );
    });
  });

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();

  await context.setOffline(true);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "You’re offline" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "当前处于离线状态" }),
  ).toBeVisible();
  await expect(
    page.getByText(/does not store papers or account data/),
  ).toBeVisible();
});
