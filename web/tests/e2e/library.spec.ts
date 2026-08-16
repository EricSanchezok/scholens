import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  libraryConversations,
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
      body: JSON.stringify({
        attention_count: 0,
        ingestion_count: 0,
        output_count: 8,
        paper_count: 27,
      }),
    }),
  );
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
  await page
    .getByRole("row")
    .filter({ hasText: "Attention Is All You Need" })
    .hover();
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
    source: { doi: "10.48550/arXiv.1706.03762", kind: "doi" },
  });
  await expect(dialog).toHaveCount(0);
  const papersTable = page.getByRole("table");
  await expect(papersTable.getByText("agentic-systems.pdf")).toBeVisible();
  await expect(papersTable.getByText("Reading PDF")).toBeVisible();

  await expect(page).toHaveTitle(/Scholens/);
  await expect
    .poll(async () => (await new AxeBuilder({ page }).analyze()).violations, {
      timeout: 5_000,
    })
    .toEqual([]);
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
