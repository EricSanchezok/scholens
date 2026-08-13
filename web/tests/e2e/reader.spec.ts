import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import path from "node:path";

import { libraryPapers } from "../../src/features/library/api/fixtures";

const apiPattern = "**/api/v1";
const paperDocument = libraryPapers[0]!.document;
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
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(paperDocument),
      }),
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/download-url`,
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
    `${apiPattern}/papers/${paperDocument.document_id}/highlight-threads`,
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
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);

  await expect(page.getByRole("toolbar", { name: "Page" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await expect(
    page.getByRole("button", { name: "Ask about selection" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask" })).toHaveCount(0);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await expect(page.locator('[data-pdf-page-number="3"]')).toBeAttached();

  await page.locator('[data-pdf-page-number="3"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await expect(page).toHaveURL(/page=3/);

  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");

  const navigationToggle = page.getByRole("button", {
    name: "Show document outline",
  });
  await navigationToggle.click();
  await expect(
    page.getByRole("button", { name: "Show page thumbnails" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Show page thumbnails" }).click();

  const pageDoesNotOwnViewportScroll = await page.evaluate(() => ({
    body: document.body.scrollHeight <= window.innerHeight,
    root:
      document.documentElement.scrollHeight <=
      document.documentElement.clientHeight,
  }));
  expect(pageDoesNotOwnViewportScroll).toEqual({ body: true, root: true });

  const selectableTextLayer = page.locator(
    '[data-pdf-page-number="2"] .pdf-text-layer',
  );
  await expect(
    selectableTextLayer.locator("span").filter({
      hasText: "The NLP landscape",
    }),
  ).toBeAttached();
  await selectableTextLayer.evaluate((textLayer) => {
    const spans = [...textLayer.querySelectorAll("span")].filter((span) =>
      span.textContent?.trim(),
    );
    const firstSpan = spans.find((span) =>
      span.textContent?.includes("The NLP landscape"),
    );
    const firstSpanIndex = firstSpan ? spans.indexOf(firstSpan) : -1;
    const lastSpan = spans[firstSpanIndex + 5];
    if (!firstSpan?.firstChild || !lastSpan?.firstChild) return;
    const range = document.createRange();
    range.setStart(firstSpan.firstChild, 0);
    range.setEnd(lastSpan.firstChild, lastSpan.textContent?.length ?? 0);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    textLayer.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  });
  const askAboutSelection = page.getByRole("button", {
    name: "Ask about selection",
  });
  await expect(askAboutSelection).toBeVisible();
  await expect(page.locator("[data-active-selection-overlay]")).toBeVisible();
  await expect(
    page.locator("[data-active-selection-overlay] canvas"),
  ).toHaveCount(1);
  const selectionColors = await page.evaluate(() => {
    const overlay = document.querySelector(
      "[data-active-selection-overlay] .pdf-selection-overlay",
    );
    const canvas = overlay instanceof HTMLCanvasElement ? overlay : undefined;
    const pixels = canvas
      ?.getContext("2d")
      ?.getImageData(0, 0, canvas.width, canvas.height).data;
    let maximumAlpha = 0;
    if (pixels) {
      for (let index = 3; index < pixels.length; index += 4) {
        maximumAlpha = Math.max(maximumAlpha, pixels[index] ?? 0);
      }
    }
    return {
      maximumAlpha,
      overlay: overlay ? getComputedStyle(overlay).color : "",
      overlayOpacity: overlay ? getComputedStyle(overlay).opacity : "",
    };
  });
  const alphaChannel = (color: string) =>
    Number(color.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/)?.[1] ?? 1);
  expect(alphaChannel(selectionColors.overlay)).toBeGreaterThanOrEqual(0.25);
  expect(alphaChannel(selectionColors.overlay)).toBeLessThanOrEqual(0.4);
  expect(selectionColors.maximumAlpha).toBeGreaterThanOrEqual(64);
  expect(selectionColors.maximumAlpha).toBeLessThanOrEqual(102);
  expect(selectionColors.overlayOpacity).toBe("1");
  await expect
    .poll(() => page.evaluate(() => window.getSelection()?.toString() ?? ""))
    .toBe("");
  await askAboutSelection.click();
  await expect(page).toHaveURL(/panel=ask/);
  await expect(page.getByText("Selection from page 2")).toBeVisible();
  await expect(askAboutSelection).toHaveCount(0);
  await expect(page.locator("[data-active-selection-overlay]")).toHaveCount(0);

  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Open context panel" }).click();
  await expect(page).toHaveURL(/panel=ask/);
  await expect(
    page.getByRole("searchbox", {
      name: "Search this paper's conversations",
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("searchbox", {
      name: "Search this paper's conversations",
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Annotations" }).click();
  await expect(page.getByText("No annotations yet")).toBeVisible();
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByText("Authors", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Open context panel" }).click();
  await expect(page.getByText("Authors", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Search PDF" }).click();
  const search = page.getByRole("textbox", { name: "Search PDF" });
  await search.fill("reasoning");
  await expect(page.getByText(/^1 \/ \d+$/)).toBeVisible();
  const currentSearchMatch = page.locator(
    '.pdf-search-match[data-search-match-current="true"]',
  );
  await expect(currentSearchMatch.first()).toBeVisible();
  await expect(currentSearchMatch.first()).toHaveText(/reasoning/i);
  expect(
    await currentSearchMatch.first().evaluate((element) => ({
      hit: element.textContent?.length ?? 0,
      textItem: element.parentElement?.textContent?.length ?? 0,
    })),
  ).toEqual(expect.objectContaining({ hit: "reasoning".length }));
  expect(
    await currentSearchMatch
      .first()
      .evaluate(
        (element) =>
          (element.parentElement?.textContent?.length ?? 0) >
          (element.textContent?.length ?? 0),
      ),
  ).toBe(true);
  const initialMatchId = await currentSearchMatch
    .first()
    .getAttribute("data-search-match-id");
  const searchColors = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const current = document.querySelector<HTMLElement>(
      '.pdf-search-match[data-search-match-current="true"]',
    );
    const other = document.querySelector<HTMLElement>(
      '.pdf-search-match:not([data-search-match-current="true"])',
    );
    return {
      current: current ? getComputedStyle(current).backgroundColor : "",
      currentToken: root
        .getPropertyValue("--color-document-search-current")
        .trim(),
      match: other ? getComputedStyle(other).backgroundColor : "",
      matchToken: root.getPropertyValue("--color-document-search-match").trim(),
    };
  });
  expect(searchColors.current).not.toBe(searchColors.match);
  expect(searchColors.currentToken).not.toBe(searchColors.matchToken);
  await page.getByRole("button", { name: "Next match" }).click();
  await expect
    .poll(() => currentSearchMatch.first().getAttribute("data-search-match-id"))
    .not.toBe(initialMatchId);
  await page.getByRole("button", { name: "Close PDF search" }).click();
  await expect(search).toBeHidden();
  await expect(page.locator(".pdf-search-match")).toHaveCount(0);

  // Development streams async root metadata independently from the Reader.
  await expect(page).toHaveTitle("Scholens");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("uses an immersive mobile Reader without the Workspace bottom navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/reader/${paperDocument.document_id}`);

  await expect(
    page.getByRole("button", { name: "Return to library" }),
  ).toBeVisible();
  await expect(
    page.locator('[data-pdf-page-number="1"] > canvas'),
  ).toBeVisible();
  await expect(page.locator("aside canvas")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Library" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Ask about selection" }),
  ).toHaveCount(0);

  const pageDoesNotOwnViewportScroll = await page.evaluate(() => ({
    body: document.body.scrollHeight <= window.innerHeight,
    root:
      document.documentElement.scrollHeight <=
      document.documentElement.clientHeight,
  }));
  expect(pageDoesNotOwnViewportScroll).toEqual({ body: true, root: true });

  await page.getByRole("button", { name: "Search PDF" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Search PDF" })).toBeVisible();
});
