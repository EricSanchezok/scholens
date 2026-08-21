import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  projectConversationFixtures,
  projectFixtures,
  projectInvitationFixtures,
  projectLibraryPaperFixtures,
  projectMemberFixtures,
  projectOutputFixtures,
  projectPaperFixtures,
} from "../../src/features/projects/api/fixtures";
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

async function mockProjects(page: Page) {
  await mockBillingUsage(page);
  let activeProject = projectFixtures[0]!;
  let paperRemoved = false;
  let invitations = [...projectInvitationFixtures];
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
  await page.route(`${apiPattern}/conversations**`, (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const turnsMatch = path.match(/\/conversations\/([^/]+)\/turns$/);
    if (turnsMatch) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          next_cursor: null,
          path_revision: 1,
        }),
      });
    }
    const conversationMatch = path.match(/\/conversations\/([^/]+)$/);
    if (conversationMatch) {
      const conversation =
        projectConversationFixtures.find(
          (item) => item.id === conversationMatch[1],
        ) ?? projectConversationFixtures[0]!;
      const update =
        request.method() === "PATCH"
          ? (request.postDataJSON() as { is_pinned?: boolean })
          : {};
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...conversation,
          ...update,
          paper_context: { kind: "library" },
          tool_permissions: [],
        }),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: projectConversationFixtures,
        next_cursor: null,
      }),
    });
  });
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
  await page.route(`${apiPattern}/project-invitations/**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ project_id: activeProject.id }),
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
    if (path.endsWith("/members") && request.method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: projectMemberFixtures,
          next_cursor: null,
        }),
      });
    }
    if (path.endsWith("/invitations") && request.method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: invitations, next_cursor: null }),
      });
    }
    if (path.endsWith("/invitations") && request.method() === "POST") {
      const body = request.postDataJSON() as {
        email: string;
        edit_project: boolean;
        manage_collaborators: boolean;
        manage_papers: boolean;
      };
      const invitation = {
        ...projectInvitationFixtures[0]!,
        email: body.email,
        id: "60000000-0000-4000-8000-000000000099",
        permissions: {
          edit_project: body.edit_project,
          manage_collaborators: body.manage_collaborators,
          manage_papers: body.manage_papers,
        },
      };
      invitations = [invitation, ...invitations];
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(invitation),
      });
    }
    if (path.endsWith("/resend") && request.method() === "POST") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(projectInvitationFixtures[0]),
      });
    }
    if (path.includes("/members/") && request.method() === "PATCH") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...projectMemberFixtures[1],
          permissions: request.postDataJSON(),
        }),
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
    if (request.method() === "DELETE" && path.includes("/papers/")) {
      const confirmed = request.headers()["x-scholens-confirmation-token"];
      if (confirmed) {
        paperRemoved = true;
        return route.fulfill({ status: 204 });
      }
      return route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          code: "confirmation_required",
          details: {
            comment_count: 5,
            confirmation_token:
              "test-confirmation-token-with-at-least-32-characters",
            thread_count: 2,
          },
          kind: "conflict",
          message: "Confirm annotation deletion",
          retryable: false,
        }),
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
          items: paperRemoved ? [] : projectPaperFixtures,
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
  await expect(
    page.getByRole("link", { name: "Truthward", exact: true }),
  ).toBeVisible();
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
  await page.getByRole("option", { name: "Name A–Z" }).click();
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

  await page.getByRole("button", { name: "Manage project" }).click();
  await page.getByRole("menuitem", { name: "Add papers" }).click();
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
  await expect(page).toHaveURL(/view=papers/);
  await expect(page).not.toHaveURL(/paper_q=|paper_cursor=|paper_sort=/);
  await expect(
    page.getByRole("link", { name: /Attention Is All You Need/ }),
  ).toHaveAttribute(
    "href",
    `/reader/${projectPaperFixtures[0]!.document_id}?project=${activeProjectId}`,
  );

  await page
    .getByRole("button", { name: "Open paper actions" })
    .first()
    .click();
  await page.getByRole("menuitem", { name: "Remove from project" }).click();
  const impactDialog = page.getByRole("alertdialog");
  await expect(impactDialog).toContainText("2 project annotation threads");
  const confirmedRemoval = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      request.method() === "DELETE" &&
      url.pathname.includes("/papers/") &&
      request.headers()["x-scholens-confirmation-token"] ===
        "test-confirmation-token-with-at-least-32-characters"
    );
  });
  await impactDialog
    .getByRole("button", { name: "Remove paper and annotations" })
    .click();
  await confirmedRemoval;
  await expect(
    page.getByRole("link", { name: /Attention Is All You Need/ }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Manage project" }).click();
  await page.getByRole("menuitem", { name: "Edit project" }).click();
  const editForm = page.getByRole("dialog");
  await editForm.getByLabel("Project name").fill("Evidence review");
  await editForm.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence review" }),
  ).toBeVisible();
  await expect(page).toHaveTitle(/Scholens/);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("invites a collaborator and accepts the emailed link", async ({
  page,
}) => {
  await page.goto(`/projects/${projectFixtures[0]!.id}`);
  await page.getByRole("button", { name: "Manage project" }).click();
  await page.getByRole("menuitem", { name: "Manage collaborators" }).click();

  const dialog = page.getByRole("dialog", { name: "Manage collaborators" });
  const inviteRegion = dialog.getByRole("region", {
    name: "Invite a collaborator",
  });
  await inviteRegion.getByLabel("Email address").fill("new@example.com");
  await inviteRegion.getByRole("checkbox", { name: "Edit project" }).check();
  const invitationRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/invitations"),
  );
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  expect((await invitationRequest).postDataJSON()).toEqual({
    edit_project: true,
    email: "new@example.com",
    manage_collaborators: false,
    manage_papers: false,
  });
  await expect(dialog.getByText("new@example.com")).toBeVisible();

  await page.goto("/project-invitations/signed.invitation-token");
  await expect(page).toHaveURL(`/projects/${projectFixtures[0]!.id}`);
  await expect(
    page.getByRole("heading", { name: projectFixtures[0]!.title }),
  ).toBeVisible();
});

test("preserves an anonymous invitation return path", async ({ page }) => {
  await page.unroute(`${apiPattern}/auth/bootstrap`);
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "auth_session_missing",
        message: "Missing",
      }),
    }),
  );

  await page.goto("/project-invitations/signed.invitation-token");

  await expect(page).toHaveURL(
    /\/login\?returnTo=%2Fproject-invitations%2Fsigned.invitation-token/,
  );
});

const activeProjectId = "20000000-0000-4000-8000-000000000099";

test("fills the desktop Project Chat panel symmetrically", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectFixtures[0]!.id}?panel=chat`);

  const chat = page.getByRole("region", { name: "Project chat" });
  const composer = chat.getByPlaceholder("Ask a follow-up");
  await expect(chat).toBeVisible();
  await expect(composer).toBeVisible();

  const chatBox = await chat.boundingBox();
  const composerBox = await composer
    .locator("xpath=ancestor::form")
    .boundingBox();
  expect(chatBox).not.toBeNull();
  expect(composerBox).not.toBeNull();

  const leftInset = composerBox!.x - chatBox!.x;
  const rightInset =
    chatBox!.x + chatBox!.width - (composerBox!.x + composerBox!.width);
  expect(Math.abs(leftInset - rightInset)).toBeLessThanOrEqual(1);
});

test("shows the complete Project collaboration roster", async ({ page }) => {
  const project = projectFixtures[0]!;
  await page.goto(`/projects/${project.id}`);

  const collaboration = page.locator("[data-project-collaboration]");
  await expect(collaboration.getByText("2 members")).toBeVisible();
  await expect(collaboration.getByText("Eric Sanchez")).toBeVisible();
  await expect(collaboration.getByText("Mina Park")).toBeVisible();
  await expect(
    collaboration.locator('[data-avatar-state="image"]'),
  ).toHaveCount(1);
});

test("opens Project Chat as a full-height mobile panel", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectFixtures[0]!.id}`);
  await expect(page.locator("[data-project-chat]")).toBeHidden();
  await page.getByRole("button", { name: "Chat" }).click();

  await expect(page).toHaveURL(/panel=chat/);
  await expect(
    page.getByRole("region", { name: "Project chat" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Close project chat" }),
  ).toBeVisible();
  const history = page
    .getByRole("button", { name: "New conversation" })
    .first();
  const create = page.getByRole("button", { name: "New conversation" }).last();
  expect((await history.boundingBox())!.x).toBeLessThan(
    (await create.boundingBox())!.x,
  );
  const composer = page.getByPlaceholder("Ask a follow-up");
  const composerBox = await composer.boundingBox();
  expect(composerBox).not.toBeNull();
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(844);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Close project chat" }).click();
  await expect(page).not.toHaveURL(/panel=chat/);
  await expect(page.getByRole("button", { name: "Chat" })).toBeFocused();
});

test("keeps the selected conversation when Project Chat closes", async ({
  page,
}) => {
  const conversationId = projectConversationFixtures[0]!.id;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    `/projects/${projectFixtures[0]!.id}?panel=chat&conversation=${conversationId}`,
  );
  await expect(
    page.getByRole("button", { name: "Compare retrieval baselines" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close project chat" }).click();
  await expect(page).toHaveURL(new RegExp(`conversation=${conversationId}`));
  await expect(page).not.toHaveURL(/panel=chat/);
});

test("does not expose Add papers without paper-management permission", async ({
  page,
}) => {
  const project = projectFixtures[0]!;
  await page.route(`${apiPattern}/projects/${project.id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...project,
        capabilities: { ...project.capabilities, manage_papers: false },
        membership: {
          ...project.membership,
          permissions: {
            ...project.membership.permissions,
            manage_papers: false,
          },
        },
      }),
    }),
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "Manage project" }).click();
  await expect(page.getByRole("menuitem", { name: "Add papers" })).toHaveCount(
    0,
  );
});

for (const width of [2560, 1440, 768, 430, 390, 320]) {
  test(`keeps Project detail within a ${width}px viewport`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/projects/${projectFixtures[0]!.id}`);
    await expect(page.locator("[data-project-title]:visible")).toHaveCount(1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(
      await page.locator("[data-project-title]").evaluateAll(
        (items) =>
          items.filter((item) => {
            const style = window.getComputedStyle(item);
            return (
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              item.getClientRects().length > 0
            );
          }).length,
      ),
    ).toBe(1);
  });
}
