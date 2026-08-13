import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  projectConversationFixtures,
  projectFixtures,
  projectLibraryPaperFixtures,
  projectOutputFixtures,
  projectPaperFixtures,
} from "../../src/features/projects/api/fixtures";

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

async function mockProjects(page: Page) {
  let activeProject = projectFixtures[0]!;
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
      body: JSON.stringify({
        items: projectConversationFixtures,
        next_cursor: null,
      }),
    }),
  );
  await page.route(`${apiPattern}/library/papers**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: projectLibraryPaperFixtures,
        next_cursor: null,
        previous_cursor: null,
        total_count: projectLibraryPaperFixtures.length,
      }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "POST" && path.endsWith("/projects")) {
      const body = request.postDataJSON() as {
        title: string;
        description: string | null;
      };
      activeProject = {
        ...projectFixtures[0]!,
        ...body,
        id: "20000000-0000-4000-8000-000000000099",
      };
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(activeProject),
      });
    }
    if (request.method() === "PATCH") {
      activeProject = {
        ...activeProject,
        ...(request.postDataJSON() as Partial<typeof activeProject>),
      };
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(activeProject),
      });
    }
    if (request.method() === "DELETE") return route.fulfill({ status: 204 });
    if (request.method() === "POST" && path.endsWith("/papers")) {
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ added_count: 1, existing_count: 0 }),
      });
    }
    if (path.endsWith("/papers")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: projectPaperFixtures,
          next_cursor: null,
          previous_cursor: null,
          total_count: projectPaperFixtures.length,
        }),
      });
    }
    if (path.endsWith("/outputs")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: projectOutputFixtures,
          next_cursor: null,
          previous_cursor: null,
          total_count: projectOutputFixtures.length,
        }),
      });
    }
    if (/\/projects\/[^/]+$/.test(path)) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(activeProject),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: projectFixtures,
        next_cursor: null,
        previous_cursor: null,
        total_count: projectFixtures.length,
      }),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockProjects(page);
});

test("supports the Projects critical journey", async ({ page }) => {
  await page.goto("/projects");

  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Truthward" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Projects" }).first(),
  ).toHaveAttribute("aria-current", "page");

  const searchRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname.endsWith("/projects") &&
      url.searchParams.get("q") === "retrieval"
    );
  });
  await page
    .getByRole("searchbox", { name: "Search projects" })
    .fill("retrieval");
  await searchRequest;
  await expect(page).toHaveURL(/q=retrieval/);
  await page.getByRole("combobox", { name: "Sort projects" }).click();
  await page.getByRole("option", { name: "Title A–Z" }).click();
  await expect(page).toHaveURL(/sort=title_asc/);

  await page.getByRole("button", { name: "New project" }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("Project name").fill("Evidence synthesis");
  await form
    .getByLabel("Description")
    .fill("A focused synthesis of retrieval evidence.");
  const createRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/v1/projects"),
  );
  await form.getByRole("button", { name: "Create project" }).click();
  expect((await createRequest).postDataJSON()).toEqual({
    description: "A focused synthesis of retrieval evidence.",
    title: "Evidence synthesis",
  });
  await expect(
    page.getByRole("heading", { name: "Evidence synthesis" }),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Papers" }).click();
  await page.getByRole("button", { name: "Add papers" }).click();
  const chooser = page.getByRole("dialog");
  await chooser
    .getByRole("checkbox", { name: /Attention Is All You Need/ })
    .check();
  const addRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/papers"),
  );
  await chooser.getByRole("button", { name: "Add 1 paper" }).click();
  expect((await addRequest).postDataJSON()).toEqual({
    document_ids: [projectPaperFixtures[0]!.document_id],
  });
  await expect(
    page.getByRole("link", { name: /Attention Is All You Need/ }),
  ).toHaveAttribute(
    "href",
    `/reader/${projectPaperFixtures[0]!.document_id}?project=${activeProjectId}`,
  );

  await page.getByRole("button", { name: "Manage project" }).click();
  await page.getByRole("menuitem", { name: "Edit project" }).click();
  const editForm = page.getByRole("dialog");
  await editForm.getByLabel("Project name").fill("Evidence review");
  await editForm.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence review" }),
  ).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

const activeProjectId = "20000000-0000-4000-8000-000000000099";

test("opens Project Chat as a full-height mobile panel", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectFixtures[0]!.id}`);
  await page.getByRole("button", { name: "Chat" }).click();

  await expect(page).toHaveURL(/panel=chat/);
  await expect(
    page.getByRole("region", { name: "Project chat" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Return to project" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
