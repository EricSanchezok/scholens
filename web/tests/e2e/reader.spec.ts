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

function annotationFixture({
  audience = { kind: "personal" },
  id,
  position,
  status = "open",
}: {
  audience?: { kind: "personal" } | { kind: "project"; project_id: string };
  id: string;
  position: {
    kind: "pdf_text";
    page_number: number;
    rects: Array<{ height: number; width: number; x: number; y: number }>;
  };
  status?: "open" | "resolved";
}) {
  return {
    id,
    kind: "annotation_thread",
    audience,
    target_document_id: paperDocument.document_id,
    created_at: "2026-08-13T12:00:00Z",
    updated_at: "2026-08-13T12:00:00Z",
    created_by: { id: actor.id, display_name: actor.display_name },
    capabilities: { delete: true, edit: true },
    annotation_thread: {
      capabilities: {
        delete: status === "open",
        recolor: true,
        reopen: status === "resolved",
        reply: status === "open",
        resolve: status === "open",
      },
      color: status === "resolved" ? "gray" : "yellow",
      comments: [
        {
          id: `${id.slice(0, -1)}9`,
          thread_id: id,
          content: "Compare this claim with the project benchmark.",
          role: "user",
          created_at: "2026-08-13T12:00:00Z",
          updated_at: "2026-08-13T12:00:00Z",
          created_by: { id: actor.id, display_name: actor.display_name },
          can_edit: true,
          can_delete: true,
        },
      ],
      position,
      quote_text: "The NLP landscape has recently been revolutionized.",
      role: "note",
      status,
      resolved_at: status === "resolved" ? "2026-08-13T12:05:00Z" : null,
      resolved_by:
        status === "resolved"
          ? { id: actor.id, display_name: actor.display_name }
          : null,
    },
  };
}

async function mockReader(page: Page) {
  const annotations: Array<Record<string, unknown>> = [];
  const project = {
    id: "50000000-0000-4000-8000-000000000001",
    title: "Agentic Web review",
    description: null,
    created_at: "2026-08-13T12:00:00Z",
    updated_at: "2026-08-13T12:00:00Z",
    num_audio_overviews: 0,
    num_collaborators: 2,
    num_conversations: 0,
    num_data_tables: 0,
    num_papers: 1,
    owner: { id: 7, display_name: "Eric", email: actor.email },
    membership: { kind: "owner", permissions: {} },
    capabilities: {
      contribute_research: true,
      create_conversation: true,
      delete: true,
      edit_project: true,
      leave: false,
      manage_collaborators: true,
      manage_papers: true,
      read: true,
      transfer: true,
    },
  };
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
    `${apiPattern}/papers/${paperDocument.document_id}/projects`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [project], next_cursor: null }),
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
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as {
          audience: { kind: "personal" | "project"; project_id?: string };
          color: string;
          initial_comment?: string;
          position: Record<string, unknown>;
          quote_text: string;
        };
        const item = {
          id: "20000000-0000-4000-8000-000000000001",
          kind: "annotation_thread",
          audience: body.audience,
          target_document_id: paperDocument.document_id,
          created_at: "2026-08-13T12:00:00Z",
          updated_at: "2026-08-13T12:00:00Z",
          created_by: { id: actor.id, display_name: actor.display_name },
          capabilities: { delete: true, edit: true },
          annotation_thread: {
            capabilities: {
              delete: true,
              recolor: true,
              reopen: false,
              reply: true,
              resolve: Boolean(body.initial_comment),
            },
            color: body.color,
            comments: body.initial_comment
              ? [
                  {
                    id: "30000000-0000-4000-8000-000000000001",
                    thread_id: "20000000-0000-4000-8000-000000000001",
                    content: body.initial_comment,
                    role: "user",
                    created_at: "2026-08-13T12:00:00Z",
                    updated_at: "2026-08-13T12:00:00Z",
                    created_by: {
                      id: actor.id,
                      display_name: actor.display_name,
                    },
                    can_edit: true,
                    can_delete: true,
                  },
                ]
              : [],
            position: body.position,
            quote_text: body.quote_text,
            role: "note",
            status: "open",
            resolved_at: null,
            resolved_by: null,
          },
        };
        annotations.unshift(item);
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(item),
        });
        return;
      }
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: annotations, next_cursor: null }),
      });
    },
  );
  await page.route("**/reader-test.pdf", (route) =>
    route.fulfill({ contentType: "application/pdf", path: pdfPath }),
  );
}

async function selectPdfPassage(page: Page, pageNumber: number) {
  const textLayer = page.locator(
    `[data-pdf-page-number="${pageNumber}"] .pdf-text-layer`,
  );
  await expect(
    textLayer.locator("span").filter({ hasText: "The NLP landscape" }),
  ).toBeAttached();
  await textLayer.evaluate((layer) => {
    const spans = [...layer.querySelectorAll("span")].filter((span) =>
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
    layer.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  });
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
  await selectPdfPassage(page, 2);
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
  await expect(
    page.getByText("What would you like to understand?"),
  ).toBeVisible();
  await expect(
    page.getByText(/paper’s claims, methods, or conclusions/),
  ).toBeVisible();
  await expect(page.getByText("Selection from page 2")).toBeVisible();
  const readerComposer = page
    .getByRole("textbox", { name: "Ask a follow-up" })
    .locator("xpath=ancestor::form");
  await expect(readerComposer).toBeVisible();
  expect(
    await readerComposer.evaluate(
      (element) => getComputedStyle(element).borderTopColor,
    ),
  ).not.toBe("rgba(0, 0, 0, 0)");
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

test("creates a persistent document highlight with the full color palette", async ({
  page,
}) => {
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await page.locator('[data-pdf-page-number="3"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await selectPdfPassage(page, 2);

  await page.getByRole("button", { name: "Highlight selection" }).click();
  const highlightPalette = page.getByRole("group", {
    name: "Highlight selection",
  });
  const swatches = highlightPalette.getByRole("button");
  await expect(swatches).toHaveCount(8);
  expect(
    await swatches.evaluateAll(
      (items) =>
        new Set(items.map((item) => getComputedStyle(item).backgroundColor))
          .size,
    ),
  ).toBe(8);

  await highlightPalette
    .getByRole("button", { name: "Yellow highlight" })
    .click();
  const persistedHighlight = page.locator(
    '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
  );
  await expect(persistedHighlight.first()).toBeVisible();
  const persistedAppearance = await persistedHighlight
    .first()
    .evaluate((element) => {
      const style = getComputedStyle(element);
      const root = getComputedStyle(document.documentElement);
      return {
        background: style.backgroundColor,
        boxShadow: style.boxShadow,
        token: root
          .getPropertyValue("--color-document-highlight-yellow")
          .trim(),
      };
    });
  expect(persistedAppearance.token).toBe("#ffd400");
  expect(persistedAppearance.background).not.toBe("rgba(0, 0, 0, 0)");
  expect(persistedAppearance.background).not.toBe("rgb(255, 255, 255)");
  expect(persistedAppearance.boxShadow).toBe("none");
  expect(
    await persistedHighlight.evaluateAll((items) =>
      items.every((item) => getComputedStyle(item).boxShadow === "none"),
    ),
  ).toBe(true);
  await page.reload();
  await expect(persistedHighlight.first()).toBeVisible();
  await expect(persistedHighlight.first()).toHaveCSS(
    "background-color",
    persistedAppearance.background,
  );
});

test("refreshes visible annotation discussions on the collaboration interval", async ({
  page,
}) => {
  let annotationReads = 0;
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "GET") annotationReads += 1;
      await route.fallback();
    },
  );
  await page.goto(
    `/reader/${paperDocument.document_id}?page=2&panel=annotations`,
  );

  await expect.poll(() => annotationReads).toBeGreaterThanOrEqual(1);
  const initialReads = annotationReads;
  await expect
    .poll(() => annotationReads, { timeout: 12_000 })
    .toBeGreaterThan(initialReads);
});

test("switches into a Project Reader and creates a project annotation atomically", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> | undefined;
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "POST") {
        createdBody = route.request().postDataJSON() as Record<string, unknown>;
      }
      await route.fallback();
    },
  );
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await page.getByRole("combobox", { name: "Reader context" }).click();
  await page.getByRole("option", { name: "Agentic Web review" }).click();
  await expect(page).toHaveURL(/project=50000000-0000-4000-8000-000000000001/);

  await selectPdfPassage(page, 2);
  await page.getByRole("button", { name: "Add annotation" }).click();
  await expect(page).toHaveURL(/panel=annotations/);
  await expect(
    page.getByRole("button", { name: "Annotations" }),
  ).toHaveAttribute("data-active", "true");
  await page
    .getByPlaceholder("Add a note to this selection")
    .fill("Compare this claim with the project benchmark.");
  await page.getByRole("button", { name: "Save annotation" }).click();
  await expect
    .poll(() => createdBody)
    .toEqual(
      expect.objectContaining({
        audience: {
          kind: "project",
          project_id: "50000000-0000-4000-8000-000000000001",
        },
        initial_comment: "Compare this claim with the project benchmark.",
      }),
    );
});

test("falls back from an inaccessible Project Reader context", async ({
  page,
}) => {
  await page.goto(
    `/reader/${paperDocument.document_id}?project=50000000-0000-4000-8000-000000000099`,
  );

  await expect(page).not.toHaveURL(/project=/);
  await expect(
    page.getByText("Switched to personal reading", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Reader context" }),
  ).toHaveText("Personal reading");
});

test("deduplicates exact anchors and reveals resolved Project discussions weakly", async ({
  page,
}) => {
  const sharedPosition = {
    kind: "pdf_text" as const,
    page_number: 2,
    rects: [{ x: 0.15, y: 0.32, width: 0.55, height: 0.035 }],
  };
  const resolvedPosition = {
    ...sharedPosition,
    rects: [{ x: 0.15, y: 0.42, width: 0.45, height: 0.035 }],
  };
  const projectId = "50000000-0000-4000-8000-000000000001";
  const seeded = [
    annotationFixture({
      id: "21000000-0000-4000-8000-000000000001",
      position: sharedPosition,
    }),
    annotationFixture({
      audience: { kind: "project", project_id: projectId },
      id: "21000000-0000-4000-8000-000000000002",
      position: sharedPosition,
    }),
    annotationFixture({
      audience: { kind: "project", project_id: projectId },
      id: "21000000-0000-4000-8000-000000000003",
      position: resolvedPosition,
      status: "resolved",
    }),
  ];
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: seeded, next_cursor: null }),
      }),
  );
  await page.goto(
    `/reader/${paperDocument.document_id}?page=2&project=${projectId}`,
  );

  const grouped = page.locator('[data-reader-annotation-count="2"]');
  await expect(grouped).toHaveCount(1);
  await expect(page.locator('[data-reader-annotation-count="1"]')).toHaveCount(
    0,
  );
  await grouped.click();
  await expect(
    page.getByRole("button", { name: "Annotations" }),
  ).toHaveAttribute("data-active", "true");
  await page.getByRole("button", { name: "Resolved" }).click();
  const resolved = page.locator(
    '[data-reader-annotation-highlight="21000000-0000-4000-8000-000000000003"]',
  );
  await expect(resolved).toBeVisible();
  expect(
    await resolved.evaluate((element) =>
      Number(getComputedStyle(element).opacity),
    ),
  ).toBeLessThan(0.4);
});

test("filters Project Ask by the current paper and preserves an unsent draft", async ({
  page,
}) => {
  const conversationRequests: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      request.url().includes("/api/v1/conversations?")
    ) {
      conversationRequests.push(request.url());
    }
  });
  await page.goto(`/reader/${paperDocument.document_id}?panel=ask`);
  const composer = page.getByRole("textbox", { name: "Ask a follow-up" });
  await composer.fill("Keep this unsent project question");
  await page.getByRole("combobox", { name: "Reader context" }).click();
  await page.getByRole("option", { name: "Agentic Web review" }).click();

  await expect(composer).toHaveValue("Keep this unsent project question");
  await expect
    .poll(() =>
      conversationRequests.some((url) => {
        const requestUrl = new URL(url);
        return (
          requestUrl.searchParams.get("scope_type") === "project" &&
          requestUrl.searchParams.get("scope_id") ===
            "50000000-0000-4000-8000-000000000001" &&
          requestUrl.searchParams.get("context_document_id") ===
            paperDocument.document_id
        );
      }),
    )
    .toBe(true);
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
