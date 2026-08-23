import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  libraryConversations,
  libraryNextPagePapers,
  libraryOutputs,
  libraryPapers,
  libraryTags,
  processingIngestion,
} from "../../src/features/library/api/fixtures";
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

async function mockLibrary(page: Page) {
  await mockBillingUsage(page);
  let tags = [...libraryTags];
  let paperListPreferences = {
    column_widths: [
      { column: "paper", width: 360 },
      { column: "status", width: 96 },
      { column: "tags", width: 160 },
      { column: "authors", width: 176 },
      { column: "publication", width: 144 },
      { column: "last_opened", width: 120 },
      { column: "added_at", width: 120 },
      { column: "doi", width: 160 },
    ],
    preview_open: true,
    preview_width: 512,
    visible_columns: [
      "status",
      "tags",
      "authors",
      "publication",
      "last_opened",
    ],
  };
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "playwright-access",
        actor,
        token_type: "bearer",
      }),
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: libraryConversations, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/me/paper-list-preferences`, async (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(paperListPreferences),
      });
    }
    if (route.request().method() === "PUT") {
      paperListPreferences = route.request().postDataJSON();
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(paperListPreferences),
      });
    }
    return route.fallback();
  });
  await page.route(`${apiPattern}/library/summary`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        attention_count: 0,
        ingestion_count: 0,
        output_count: 8,
        paper_count: 27,
      }),
    }),
  );
  await page.route(`${apiPattern}/me/paper-list-preferences`, async (route) => {
    if (route.request().method() === "PUT") {
      paperListPreferences = route.request().postDataJSON();
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(paperListPreferences),
    });
  });
  await page.route(`${apiPattern}/library/tags**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: tags, next_cursor: null }),
      });
    }
    if (request.method() === "POST" && pathname.endsWith("/library/tags")) {
      const body = request.postDataJSON() as { name: string };
      const created = {
        color: null,
        id: "71000000-0000-4000-8000-000000000099",
        name: body.name,
      };
      tags = [...tags, created];
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(created),
      });
    }
    if (
      request.method() === "PUT" &&
      pathname.endsWith("/library/tags/assignments")
    ) {
      const body = request.postDataJSON() as { document_ids: string[] };
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          updated_paper_count: body.document_ids.length,
        }),
      });
    }
    return route.fallback();
  });
  await page.route(`${apiPattern}/library/papers**`, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor ? [libraryNextPagePapers[0]] : libraryPapers,
        next_cursor: cursor ? null : "next-library-page",
        previous_cursor: cursor ? "previous-library-page" : null,
        total_count: 27,
      }),
    });
  });
  await page.route(`${apiPattern}/search/papers`, (route) => {
    const paper = libraryPapers[1]!;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            abstract:
              "Retrieval-augmented generation combines parametric and non-parametric memory.",
            authors: paper.document.authors,
            created_at: paper.document.created_at,
            document_id: paper.document.document_id,
            keywords: ["retrieval-augmented generation"],
            last_accessed_at: paper.last_accessed_at,
            matched_fields: ["title", "abstract"],
            preview_url: null,
            publish_date: null,
            retrieval_modes: ["full_text", "semantic"],
            snippets: [
              {
                text: "Retrieval-augmented generation for knowledge-intensive tasks.",
              },
            ],
            status: paper.document.processing_status,
            summary: null,
            title: paper.document.title,
          },
        ],
        next_cursor: null,
        search_mode: "hybrid",
        semantic_index_coverage: 1,
        total: 1,
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
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          headers: {
            "content-type": "application/pdf",
            "x-amz-checksum-sha256": "test-checksum",
          },
          max_bytes: 31_457_280,
          method: "PUT",
          next_step: "upload_pdf_then_call_ingest_paper_with_upload_id",
          session_expires_at: "2026-08-17T02:00:00Z",
          upload_id: "00000000-0000-4000-8000-000000000088",
          upload_url: "http://127.0.0.1:7301/mock-paper-upload",
          upload_url_expires_at: "2026-08-16T02:15:00Z",
        }),
      });
    }
    if (pathname.endsWith("/paper-ingestions/sources")) {
      const body = request.postDataJSON() as {
        source: { kind: string };
      };
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(
          body.source.kind === "upload"
            ? {
                ...processingIngestion,
                display_name: "local-paper.pdf",
                id: "00000000-0000-4000-8000-000000000090",
                source_kind: "upload",
                stage: "queued",
                state: "queued",
              }
            : processingIngestion,
        ),
      });
    }
    return route.fallback();
  });
  await page.route("**/mock-paper-upload", (route) =>
    route.fulfill({ status: 200 }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockLibrary(page);
});

test("keeps the mobile filter controls readable without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ height: 852, width: 384 });
  await page.route(`${apiPattern}/library/summary`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        attention_count: 0,
        ingestion_count: 1,
        output_count: 8,
        paper_count: 27,
      }),
    }),
  );
  await page.goto("/library");

  const search = page.getByRole("searchbox", { name: "Search papers" });
  const statusButton = page.getByRole("button", {
    exact: true,
    name: "Status",
  });
  const tagButton = page.getByRole("button", { exact: true, name: "Tags" });
  const sort = page.getByRole("combobox", { name: "Sort papers" });
  const count = page.getByText("27 papers", { exact: true });
  await expect(search).toBeVisible();
  await expect(statusButton).toBeVisible();
  await expect(tagButton).toBeVisible();
  await expect(sort).toBeVisible();
  await expect(count).toBeHidden();

  const [searchBox, statusBox, tagBox, sortBox, overflow] = await Promise.all([
    search.boundingBox(),
    statusButton.boundingBox(),
    tagButton.boundingBox(),
    sort.boundingBox(),
    page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ]);
  const tops = [searchBox, statusBox, tagBox, sortBox].map((box) => box!.y);
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1);
  expect(
    await page
      .locator("[data-collection-toolbar]")
      .evaluate((toolbar) => toolbar.scrollWidth <= toolbar.clientWidth),
  ).toBe(true);
  await expect(
    search.locator("xpath=ancestor::*[@data-slot='frame']"),
  ).toHaveCount(0);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("keeps Library output controls on one mobile row", async ({ page }) => {
  await page.setViewportSize({ height: 852, width: 320 });
  await page.goto("/library?tab=outputs");
  const search = page.getByRole("searchbox", { name: "Search outputs" });
  const kinds = page.getByRole("button", { name: "Types" });
  const sort = page.getByRole("combobox", { name: "Sort outputs" });
  const boxes = await Promise.all([
    search.boundingBox(),
    kinds.boundingBox(),
    sort.boundingBox(),
  ]);
  const tops = boxes.map((box) => box!.y);
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1);
  expect(
    await search
      .locator("xpath=ancestor::*[@data-collection-toolbar]")
      .evaluate((toolbar) => toolbar.scrollWidth <= toolbar.clientWidth),
  ).toBe(true);
  await expect(
    search.locator("xpath=ancestor::*[@data-slot='frame']"),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("loads the tag catalog only when tag controls are requested", async ({
  page,
}) => {
  let tagReads = 0;
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      new URL(request.url()).pathname.endsWith("/api/v1/library/tags")
    ) {
      tagReads += 1;
    }
  });
  await page.goto("/library");
  await expect(page.getByRole("table")).toBeVisible();
  expect(tagReads).toBe(0);

  await page.getByRole("button", { name: "Tags" }).click();
  await expect(
    page.getByRole("checkbox", { name: libraryTags[0]!.name }),
  ).toBeVisible();
  expect(tagReads).toBe(1);
});

test("opens paper details as a full-height Library side panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/library");

  const layout = page.locator("[data-paper-collection-page-layout]");
  const preview = page.getByRole("complementary", { name: "Paper details" });
  await expect(preview).toBeVisible();
  const [layoutBox, previewBox] = await Promise.all([
    layout.boundingBox(),
    preview.boundingBox(),
  ]);
  expect(Math.abs(previewBox!.y - layoutBox!.y)).toBeLessThanOrEqual(1);
  expect(
    Math.abs(
      previewBox!.y + previewBox!.height - (layoutBox!.y + layoutBox!.height),
    ),
  ).toBeLessThanOrEqual(1);
  await expect(
    preview.getByRole("button", { name: "Close paper details" }),
  ).toHaveCount(0);

  const lastOpenedHeader = page.getByRole("columnheader", {
    exact: true,
    name: "Last opened",
  });
  const table = page.getByRole("table");
  const [lastOpenedBox, tableBox] = await Promise.all([
    lastOpenedHeader.boundingBox(),
    table.boundingBox(),
  ]);
  expect(lastOpenedBox).not.toBeNull();
  expect(tableBox).not.toBeNull();
  expect(lastOpenedBox!.x + lastOpenedBox!.width).toBeLessThanOrEqual(
    tableBox!.x + tableBox!.width,
  );

  const toggle = page.locator("[data-paper-preview-toggle]");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await toggle.click();
  await expect(preview).toHaveCount(0);
  await expect(toggle).toHaveAttribute("aria-label", "Show paper details");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(toggle).toBeFocused();

  await toggle.click();
  await expect(preview).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-label", "Close paper details");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
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
  await page.getByRole("row").filter({ has: firstPaper }).hover();
  await expect(firstPaper).toBeVisible();
  await firstPaper.click();
  await expect(page.getByText("1 paper selected")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove from library" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Add to project · Not available yet",
    }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Edit tags" }).click();
  const tagDialog = page.getByRole("dialog");
  await tagDialog.getByLabel("New tag name").fill("Reading queue");
  await tagDialog.getByRole("button", { name: "Create" }).click();
  await expect(tagDialog.getByText("Reading queue")).toBeVisible();
  const assignmentRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/api/v1/library/tags/assignments"),
  );
  await tagDialog.getByRole("button", { name: "Apply tags" }).click();
  expect((await assignmentRequest).postDataJSON()).toEqual({
    document_ids: [libraryPapers[0]!.document.document_id],
    tag_ids: [libraryTags[0]!.id, "71000000-0000-4000-8000-000000000099"],
  });
  await expect(page.getByText("1 paper selected")).toHaveCount(0);

  const searchbox = page.getByRole("searchbox", { name: "Search papers" });
  const searchRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/search/papers"),
  );
  await searchbox.fill("retrieval");
  expect((await searchRequest).postDataJSON()).toEqual({
    collection: { kind: "personal_library" },
    filters: {
      personal_statuses: [],
      personal_tag_ids: [],
    },
    limit: 50,
    query: "retrieval",
    sort: "relevance",
  });
  await expect(page).toHaveURL(/q=retrieval/);
  await expect(
    page.getByRole("link", {
      name: /Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks/,
    }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Previous" })).toHaveCount(0);
  await searchbox.fill("");
  await expect(page).not.toHaveURL(/q=retrieval/);

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
    source: { doi: "10.48550/arXiv.1706.03762", kind: "doi" },
  });
  await expect(dialog).toHaveCount(0);
  const ingestionRow = page.locator("[data-ingestion-row]");
  await expect(ingestionRow.getByText("agentic-systems.pdf")).toBeVisible();
  await expect(ingestionRow.getByText("Reading PDF")).toBeVisible();

  await expect(page).toHaveTitle(/Scholens/);
  await expect
    .poll(async () => (await new AxeBuilder({ page }).analyze()).violations, {
      timeout: 5_000,
    })
    .toEqual([]);
});

test("keeps Library chrome fixed while switching between Papers and Outputs", async ({
  page,
}) => {
  for (const width of [1440, 2560]) {
    await page.setViewportSize({ height: 1000, width });
    await page.goto("/library");
    const heading = page.getByRole("heading", { name: "Library" });
    const header = heading.locator("xpath=ancestor::header");
    const addPapers = page.getByRole("button", { name: "Add papers" });
    const paperSearch = page.getByRole("searchbox", { name: "Search papers" });
    await expect(page.getByRole("table")).toBeVisible();
    const before = {
      addPapers: await addPapers.boundingBox(),
      header: await header.boundingBox(),
      search: await paperSearch.boundingBox(),
    };

    await page.getByRole("tab", { name: /^Outputs/ }).click();
    await expect(page).toHaveURL(/tab=outputs/);
    await expect(
      page.getByRole("table").getByText("Architecture notes"),
    ).toBeVisible();
    const after = {
      addPapers: await addPapers.boundingBox(),
      header: await header.boundingBox(),
      search: await page
        .getByRole("searchbox", { name: "Search outputs" })
        .boundingBox(),
    };

    expect(before.header).not.toBeNull();
    expect(before.addPapers).not.toBeNull();
    expect(before.search).not.toBeNull();
    expect(after.header).not.toBeNull();
    expect(after.addPapers).not.toBeNull();
    expect(after.search).not.toBeNull();
    if (
      !before.header ||
      !before.addPapers ||
      !before.search ||
      !after.header ||
      !after.addPapers ||
      !after.search
    ) {
      throw new Error(
        "Expected Library layout elements to have bounding boxes",
      );
    }
    expect(after.header.x).toBeCloseTo(before.header.x, 0);
    expect(after.header.width).toBeCloseTo(before.header.width, 0);
    expect(after.addPapers.x).toBeCloseTo(before.addPapers.x, 0);
    expect(after.search.x).toBeCloseTo(before.search.x, 0);
  }
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
      buffer: Buffer.from("%PDF-1.7\nremove-before-upload\n%%EOF"),
    },
  ]);
  await expect(dialog.getByText("local-paper.pdf")).toBeVisible();
  await dialog
    .getByRole("button", { name: "Remove remove-before-upload.pdf" })
    .click();

  const prepareRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/paper-ingestions/uploads"),
  );
  const uploadRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/mock-paper-upload"),
  );
  const ingestionRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/paper-ingestions/sources"),
  );
  await dialog.getByRole("button", { name: "Upload 1 file" }).click();
  const preparedRequest = await prepareRequest;
  const preparedBody = preparedRequest.postDataJSON() as {
    filename: string;
    sha256: string;
    size_bytes: number;
  };
  expect(preparedBody.filename).toBe("local-paper.pdf");
  expect(preparedBody.size_bytes).toBe(Buffer.byteLength("%PDF-1.7\n%%EOF"));
  expect(preparedBody.sha256).toMatch(/^[0-9a-f]{64}$/);
  const transferRequest = await uploadRequest;
  expect(transferRequest.headers()["authorization"]).toBeUndefined();
  expect(transferRequest.headers()["content-type"]).toBe("application/pdf");
  const acceptedRequest = await ingestionRequest;
  expect(acceptedRequest.headers()["idempotency-key"]).toBeTruthy();
  expect(acceptedRequest.postDataJSON()).toEqual({
    source: {
      kind: "upload",
      upload_id: "00000000-0000-4000-8000-000000000088",
    },
  });
  await expect(dialog).toHaveCount(0);
  const ingestionRow = page.locator("[data-ingestion-row]");
  await expect(ingestionRow.getByText("local-paper.pdf")).toBeVisible();
  await expect(ingestionRow.getByText("Waiting to process")).toBeVisible();

  const cancelRequest = page.waitForRequest(
    (request) =>
      request.method() === "DELETE" &&
      request
        .url()
        .includes("/paper-ingestions/00000000-0000-4000-8000-000000000090"),
  );
  await ingestionRow.getByRole("button", { name: "Cancel processing" }).click();
  await cancelRequest;
  await expect(ingestionRow.getByText("local-paper.pdf")).toHaveCount(0);
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
    await expect(
      page
        .locator(`a[href="/reader/${libraryPapers[0]!.document.document_id}"]`)
        .filter({ visible: true }),
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
