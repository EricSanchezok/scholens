import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  libraryConversations,
  libraryOutputs,
  libraryPapers,
  libraryProjects,
  libraryTags,
  processingIngestion,
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
  await page.route(`${apiPattern}/library/outputs**`, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor ? [libraryOutputs[3]] : libraryOutputs,
        next_cursor: cursor ? null : "next-output-page",
        previous_cursor: cursor ? "previous-output-page" : null,
        total_count: 8,
      }),
    });
  });
  await page.route(`${apiPattern}/paper-ingestions/**`, (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "DELETE") {
      return route.fulfill({ status: 204 });
    }
    if (pathname.endsWith("/paper-ingestions/uploads")) {
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          ...processingIngestion,
          display_name: "local-paper.pdf",
          id: "00000000-0000-4000-8000-000000000090",
          source_kind: "upload",
          stage: "queued",
          state: "queued",
        }),
      });
    }
    if (pathname.endsWith("/paper-ingestions/sources")) {
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(processingIngestion),
      });
    }
    return route.fallback();
  });
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
  await expect(dialog).toHaveCount(0);
  const papersTable = page.getByRole("table");
  await expect(papersTable.getByText("agentic-systems.pdf")).toBeVisible();
  await expect(papersTable.getByText("Reading PDF")).toBeVisible();

  await expect(page).toHaveTitle(/Scholens/);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("moves accepted uploads into paper rows and supports cancellation", async ({
  page,
}) => {
  await page.goto("/library");
  await page.getByRole("button", { name: "Add papers" }).click();
  const dialog = page.getByRole("dialog");
  const input = dialog.getByLabel("Choose PDFs");
  await input.setInputFiles([
    {
      name: "local-paper.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.7\n%%EOF"),
    },
    {
      name: "remove-before-upload.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.7\n%%EOF"),
    },
  ]);
  await expect(dialog.getByText("local-paper.pdf")).toBeVisible();
  await dialog
    .getByRole("button", { name: "Remove remove-before-upload.pdf" })
    .click();

  const uploadRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/paper-ingestions/uploads"),
  );
  await dialog.getByRole("button", { name: "Upload 1 file" }).click();
  const acceptedRequest = await uploadRequest;
  expect(acceptedRequest.headers()["idempotency-key"]).toBeTruthy();
  await expect(dialog).toHaveCount(0);
  const papersTable = page.getByRole("table");
  await expect(papersTable.getByText("local-paper.pdf")).toBeVisible();
  await expect(papersTable.getByText("Waiting to process")).toBeVisible();

  const cancelRequest = page.waitForRequest(
    (request) =>
      request.method() === "DELETE" &&
      request
        .url()
        .includes("/paper-ingestions/00000000-0000-4000-8000-000000000090"),
  );
  await papersTable.getByRole("button", { name: "Cancel processing" }).click();
  await cancelRequest;
  await expect(papersTable.getByText("local-paper.pdf")).toHaveCount(0);
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

test("supports filtered Outputs without creating dead-end navigation", async ({
  page,
}) => {
  await page.goto("/library?tab=outputs");

  const table = page.getByRole("table");
  await expect(table).toBeVisible();
  await expect(table.getByText("Architecture notes")).toBeVisible();
  await expect(table.getByText("Transformer citation")).toBeVisible();
  await expect(table.getByText("Retrieval methods overview")).toBeVisible();
  await expect(table.getByText("Model comparison")).toBeVisible();

  await page.getByRole("button", { name: "Types" }).click();
  await page.getByRole("checkbox", { name: "Citations" }).click();
  await expect(page).toHaveURL(/kind=citation/);

  await page.getByRole("combobox", { name: "Sort outputs" }).click();
  await page.getByRole("option", { name: "Title Z–A" }).click();
  await expect(page).toHaveURL(/sort=title_desc/);

  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/cursor=next-output-page/);
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();

  const unavailable = table.getByRole("button", {
    name: "Not available yet",
  });
  await expect(unavailable).toHaveCount(1);
  await expect(unavailable).toBeDisabled();
  await expect(
    page.getByRole("link", { name: /Not available yet/ }),
  ).toHaveCount(0);

  // Next streams async route metadata independently from the page shell in
  // development. Wait for the document title before running a full-page audit.
  await expect(page).toHaveTitle("Scholens");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("contains Outputs at 320, 390, and 430 pixels", async ({ page }) => {
  for (const width of [320, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/library?tab=outputs");
    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(
      page.getByText("Architecture notes").filter({ visible: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    const contained = await page
      .locator('input[aria-label="Search outputs"], main li')
      .evaluateAll((elements) =>
        elements
          .filter((element) => element.getClientRects().length > 0)
          .every((element) => {
            const rect = element.getBoundingClientRect();
            return rect.left >= 0 && rect.right <= window.innerWidth;
          }),
      );
    expect(contained).toBe(true);
  }

  await page.getByRole("button", { name: "Types" }).click();
  const sheet = page.getByRole("dialog");
  await expect(
    sheet.getByRole("checkbox", { name: "Audio overviews" }),
  ).toBeVisible();
});
