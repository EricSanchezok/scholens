import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import path from "node:path";

import { libraryPapers } from "../../src/features/library/api/fixtures";

const apiPattern = "**/api/v1";
const document = libraryPapers[0]!.document;
const pdfPath = path.resolve(
  "../server/evals/seed_data/chain_of_thought_for_reasoning.pdf",
);
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

async function mockReader(page: Page) {
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
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/papers/${document.document_id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(document),
    }),
  );
  await page.route(
    `${apiPattern}/papers/${document.document_id}/download-url`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          expires_in_seconds: 300,
          file_url: "http://127.0.0.1:7300/reader-test.pdf",
        }),
      }),
  );
  await page.route(
    `${apiPattern}/papers/${document.document_id}/highlight-threads`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [], next_cursor: null }),
      }),
  );
  await page.route("**/reader-test.pdf", (route) =>
    route.fulfill({ contentType: "application/pdf", path: pdfPath }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockReader(page);
});

test("opens a Library paper in the desktop Reader and restores route state", async ({
  page,
}) => {
  await page.goto(`/reader/${document.document_id}?page=2`);

  await expect(page.getByRole("toolbar", { name: "Page" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await expect(
    page.locator(".shadow-raised.bg-surface > canvas"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Search PDF" }).click();
  const search = page.getByRole("searchbox", { name: "Search this PDF" });
  await search.fill("reasoning");
  await expect(page.getByText(/match/).first()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(search).toBeHidden();
  await page.getByRole("button", { name: "Open context panel" }).click();
  await expect(page).toHaveURL(/panel=ask/);
  await page.getByRole("button", { name: "Annotations" }).click();
  await expect(page.getByText("No annotations yet")).toBeVisible();

  // Development streams async root metadata independently from the Reader.
  await expect(page).toHaveTitle("Scholens");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("uses an immersive mobile Reader without the Workspace bottom navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/reader/${document.document_id}`);

  await expect(
    page.getByRole("button", { name: "Return to library" }),
  ).toBeVisible();
  await expect(
    page.locator(".shadow-raised.bg-surface > canvas"),
  ).toBeVisible();
  await expect(page.locator("aside canvas")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Library" })).toHaveCount(0);

  await page.getByRole("button", { name: "Search PDF" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("searchbox", { name: "Search this PDF" }),
  ).toBeVisible();
});
