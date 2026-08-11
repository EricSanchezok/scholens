import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  libraryConversations,
  libraryPapers,
  libraryProjects,
  libraryTags,
  processingJob,
} from "../../src/features/library/api/fixtures";

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

async function mockLibrary(page: Page) {
  await page.route(`${apiPattern}/auth/refresh`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "playwright-access",
        token_type: "bearer",
      }),
    }),
  );
  await page.route(`${apiPattern}/me`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(actor),
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: libraryConversations, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/summary`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ paper_count: 27, output_count: 8 }),
    }),
  );
  await page.route(`${apiPattern}/library/tags`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: libraryTags, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: libraryProjects, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/jobs**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers**`, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor ? [libraryPapers[2]] : libraryPapers,
        next_cursor: cursor ? null : "next-library-page",
        previous_cursor: cursor ? "previous-library-page" : null,
        total_count: 27,
      }),
    });
  });
  await page.route(`${apiPattern}/paper-ingestions/sources`, (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(processingJob),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockLibrary(page);
});

test("supports the Library Papers critical journey", async ({ page }) => {
  await page.goto("/library");

  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Library" }).first(),
  ).toHaveAttribute("aria-current", "page");

  const firstPaper = page.getByRole("checkbox", {
    name: "Select Attention Is All You Need",
  });
  await firstPaper.click();
  await expect(page.getByText("1 paper selected")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove from library" }),
  ).toBeVisible();

  const searchRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname.endsWith("/library/papers") &&
      url.searchParams.get("q") === "retrieval"
    );
  });
  await page
    .getByRole("searchbox", { name: "Search papers" })
    .fill("retrieval");
  await searchRequest;
  await expect(page).toHaveURL(/q=retrieval/);
  await expect(page.getByText("1 paper selected")).toHaveCount(0);

  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/cursor=next-library-page/);
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();

  await page.getByRole("button", { name: "Add papers" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Add papers" }),
  ).toBeVisible();
  await dialog
    .getByRole("textbox", { name: "Source", exact: true })
    .fill("10.48550/arXiv.1706.03762");
  const sourceRequest = page.waitForRequest((request) =>
    request.url().endsWith("/api/v1/paper-ingestions/sources"),
  );
  await dialog.getByRole("button", { name: "Add source" }).click();
  expect((await sourceRequest).postDataJSON()).toEqual({
    source: { kind: "doi", value: "10.48550/arXiv.1706.03762" },
  });

  await expect(page).toHaveTitle(/Scholens/);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("restores URL state and contains each supported phone width", async ({
  page,
}) => {
  await page.goto(`/library?sort=title_asc&tag=${libraryTags[0]!.id}`);
  await expect(
    page.getByRole("combobox", { name: "Sort papers" }),
  ).toContainText("Title A–Z");

  for (const width of [320, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/library");
    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(
      page
        .getByRole("listitem")
        .filter({ hasText: "Attention Is All You Need", visible: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }

  await page.getByRole("button", { name: "Tags" }).click();
  const sheet = page.getByRole("dialog");
  await expect(
    sheet.getByRole("checkbox", { name: "Transformers" }),
  ).toBeVisible();
});
