import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page, test } from "@playwright/test";

async function expectMinimumTouchTargets(locator: Locator) {
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    expect(
      await locator
        .nth(index)
        .evaluate((element) => element.getBoundingClientRect().height),
    ).toBeGreaterThanOrEqual(44);
  }
}

async function mockAnonymousSession(page: Page) {
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "auth_session_missing",
        message: "session missing",
      }),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockAnonymousSession(page);
});

test("publishes an anonymous, accessible MCP setup guide", async ({ page }) => {
  const response = await page.goto("/docs");

  expect(response?.headers().link).toContain(
    '</docs.md>; rel="alternate"; type="text/markdown"',
  );
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Connect your research agent to Scholens",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Create access key/ }),
  ).toHaveAttribute("href", "/?settings=access-keys");
  await expect(
    page.locator("code").filter({ hasText: "/mcp" }).first(),
  ).toBeVisible();
  await expect(
    page.getByText(
      /secure access to 56 tools for your stored research knowledge/,
    ),
  ).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("keeps the selected client in the URL", async ({ page }) => {
  await page.goto("/docs");
  await page.getByRole("link", { name: "Cursor" }).click();

  await expect(page).toHaveURL(/\/docs\?client=cursor$/);
  await expect(
    page.getByText("Bearer ${env:SCHOLENS_ACCESS_KEY}", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Cursor" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("preserves the Access Keys destination through sign-in", async ({
  page,
}) => {
  let signedIn = false;
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: signedIn ? 200 : 401,
      contentType: "application/json",
      body: JSON.stringify(
        signedIn
          ? {
              access_token: "playwright-access",
              token_type: "bearer",
            }
          : {
              code: "auth_session_missing",
              message: "session missing",
            },
      ),
    }),
  );
  await page.route("**/api/v1/auth/login", (route) => {
    signedIn = true;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "playwright-access",
        token_type: "bearer",
      }),
    });
  });
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: 7,
        email: "researcher@example.com",
        email_verified: true,
        is_active: true,
        is_admin: false,
        is_blocked: false,
        status: "active",
        display_name: "Researcher",
        locale: "en",
      }),
    }),
  );
  await page.route("**/api/v1/me/access-keys", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    }),
  );

  await page.goto("/docs");
  await page.getByRole("link", { name: /Create access key/ }).click();
  await expect(page).toHaveURL("/login?returnTo=%2F%3Fsettings%3Daccess-keys");

  await page.getByLabel("Email").fill("researcher@example.com");
  await page.getByRole("textbox", { name: "Password" }).fill("twelve-chars!");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL("/?settings=access-keys");
  await expect(
    page.getByRole("heading", { level: 2, name: "Access keys" }),
  ).toBeVisible();
});

test("serves machine-readable documentation without authentication", async ({
  request,
}) => {
  const markdown = await request.get("/docs.md");
  expect(markdown.ok()).toBe(true);
  expect(markdown.headers()["content-type"]).toBe(
    "text/markdown; charset=utf-8",
  );
  expect(await markdown.text()).toContain("# Scholens MCP setup");

  const llms = await request.get("/llms.txt");
  expect(llms.ok()).toBe(true);
  expect(llms.headers()["content-type"]).toBe("text/plain; charset=utf-8");
  expect(await llms.text()).toContain("Complete machine-readable MCP guide");
});

test("fits the guide at the minimum supported width", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/docs?client=claude-desktop");

  const compactToc = page
    .locator("summary")
    .filter({ hasText: "On this page" });
  await expect(compactToc).toBeVisible();
  await compactToc.click();

  const touchTargetGroups = [
    page
      .getByRole("group", { name: "Documentation language" })
      .getByRole("button"),
    page.getByRole("link", { name: "Scholens / Docs", exact: true }),
    page.locator("details").first().getByRole("link"),
    page.getByRole("link", {
      name: "Open the client's official MCP documentation",
    }),
    page.locator("summary"),
    page.locator("footer a"),
  ];
  for (const targets of touchTargetGroups) {
    await expectMinimumTouchTargets(targets);
  }

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
