import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  homeConversations,
  homePapers,
  homeProjects,
  homeTurns,
} from "../../src/features/home/api/fixtures";
import { mockBillingUsage } from "./billing-fixture";

const apiPattern = "**/api/v1";
type ConversationTurn = (typeof homeTurns)[number];
const firstPaper = homePapers[0]!.document;
const actor = {
  id: 7,
  email: "niexiaohangeric@163.com",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "EricSanchez",
  locale: "en",
};

async function mockHome(page: Page) {
  await mockBillingUsage(page);
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
      body: JSON.stringify({ items: homeConversations, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: homePapers, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: homeProjects, next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/search/conversations`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            conversation: homeConversations[0],
            matched_field: "assistant_response",
            snippet: "A selected answer about retrieval memory.",
          },
        ],
        next_cursor: null,
        total: 1,
      }),
    }),
  );
  await page.route(`${apiPattern}/search/papers`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            created_at: firstPaper.created_at,
            document_id: firstPaper.document_id,
            last_accessed_at: homePapers[0]!.last_accessed_at,
            preview_url: homePapers[0]!.preview_url,
            publish_date: firstPaper.publish_date,
            status: firstPaper.processing_status,
            summary: firstPaper.summary,
            title: firstPaper.title,
            abstract: "A paper about retrieval memory.",
            authors: ["Researcher One"],
            matched_fields: ["title"],
            retrieval_modes: ["exact"],
            snippets: [{ text: "Retrieval memory evidence." }],
          },
        ],
        next_cursor: null,
        search_mode: "exact",
        semantic_index_coverage: 1,
        total: 1,
      }),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockHome(page);
});

test("account menu exposes live usage and direct Settings destinations", async ({
  page,
}) => {
  await page.goto("/");
  const accountMenu = page.getByRole("button", { name: "Open account menu" });
  await accountMenu.click();
  const menu = page.getByRole("menu");
  await expect(menu.getByText("Researcher")).toBeVisible();
  await expect(menu.getByText("24M / 100M")).toBeVisible();
  await expect(menu.getByText("Credits reset on Aug 17, 2026")).toBeVisible();
  await expect(
    menu.getByRole("menuitem", { name: "Repository" }),
  ).toHaveAttribute("href", "https://github.com/EricSanchezok/scholens");
  await expect(
    menu.getByRole("menuitem", { name: "Repository" }),
  ).toHaveAttribute("target", "_blank");
  await expect(
    menu.getByRole("menuitem", { name: "Documentation" }),
  ).toHaveAttribute("href", "/docs");
  await expect(
    menu.getByRole("menuitem", { name: "Documentation" }),
  ).toHaveAttribute("target", "_blank");

  await menu.getByRole("menuitem", { name: "Account" }).click();
  await expect(page).toHaveURL(/\?settings=account$/);

  await page.goto("/");
  await accountMenu.click();
  await page.getByRole("menuitem", { name: "Usage" }).click();
  await expect(page).toHaveURL(/\?settings=usage$/);
});

test("links Access Keys to the public MCP setup guide", async ({ page }) => {
  await page.route(`${apiPattern}/me/access-keys`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    }),
  );
  await page.goto("/?settings=access-keys");

  await expect(
    page.getByRole("link", { name: /MCP setup guide/ }),
  ).toHaveAttribute("href", "/docs#mcp-setup");
  await expect(
    page.getByRole("link", { name: /MCP setup guide/ }),
  ).toHaveAttribute("target", "_blank");
});

test("renders the authenticated Home shell and primary data", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Attention Is All You Need" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Thesis literature review" }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "default");
  await expect(page.locator("html")).toHaveAttribute(
    "data-color-scheme",
    /light|dark/,
  );
  expect(
    await page.evaluate(() => {
      const root = document.scrollingElement;
      return root ? root.scrollHeight <= root.clientHeight : false;
    }),
  ).toBe(true);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("opens one keyboard-search surface for conversations and papers", async ({
  page,
}) => {
  await page.goto("/");
  const trigger = page.getByRole("button", {
    name: "Search conversations and papers (⌘K)",
  });
  await trigger.focus();
  await page.keyboard.press("Control+K");
  const dialog = page.getByRole("dialog", { name: "Search Scholens" });
  await expect(dialog).toBeVisible();
  const input = dialog.getByRole("searchbox", {
    name: "Search conversations or papers",
  });
  await input.fill("memory");
  const conversationResult = dialog.getByRole("link", {
    name: new RegExp(homeConversations[0]!.title),
  });
  await expect(conversationResult).toBeVisible();
  await input.press("ArrowDown");
  await expect(conversationResult).toBeFocused();

  await dialog.getByRole("tab", { name: "Papers" }).click();
  await expect(
    dialog.getByRole("link", {
      name: new RegExp(firstPaper.title ?? "Untitled paper"),
    }),
  ).toBeVisible();
  const accessibility = await new AxeBuilder({ page })
    .include('[role="dialog"]')
    .analyze();
  expect(accessibility.violations).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("renders an intentional first-run Home without empty card shells", async ({
  page,
}) => {
  await page.unroute(`${apiPattern}/conversations**`);
  await page.unroute(`${apiPattern}/library/papers`);
  await page.unroute(`${apiPattern}/projects**`);
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/library/papers`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );

  await page.goto("/");
  await expect(page.getByText(/Ask across a paper/)).toBeVisible();
  await expect(page.getByText("Recent papers", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Recent projects", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Your conversations will appear here."),
  ).toBeVisible();

  const composer = page.getByRole("textbox", { name: "Ask anything" });
  const submit = page.getByRole("button", { name: "Ask Scholens" });
  await composer.click();
  await expect
    .poll(() =>
      composer.evaluate((element) => getComputedStyle(element).outlineStyle),
    )
    .toBe("none");
  await expect
    .poll(() =>
      submit.evaluate((element) => {
        const icon = element.querySelector("svg");
        return icon
          ? getComputedStyle(icon).color === getComputedStyle(element).color
          : false;
      }),
    )
    .toBe(true);
});

test("lets the Server generate the initial conversation title", async ({
  page,
}) => {
  await page.goto("/");
  const creation = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/conversations"),
  );

  await page.getByRole("textbox", { name: "Ask anything" }).fill("Study RAG");
  await page.getByRole("button", { name: "Ask Scholens" }).click();

  expect((await creation).postDataJSON()).toEqual({
    scope_type: "global",
    paper_context: { kind: "library" },
  });
});

test("keeps an IME candidate-confirmation Enter in the Composer", async ({
  page,
}) => {
  const creations: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/conversations")
    ) {
      creations.push(request.url());
    }
  });

  await page.goto("/");
  const composer = page.getByRole("textbox", { name: "Ask anything" });
  await composer.fill("你好");
  await composer.dispatchEvent("compositionstart", { data: "你" });
  await composer.dispatchEvent("keydown", {
    code: "Enter",
    isComposing: true,
    key: "Enter",
    keyCode: 229,
  });
  await composer.dispatchEvent("compositionend", { data: "你好" });

  await expect(composer).toHaveValue("你好");
  expect(creations).toHaveLength(0);

  await composer.press("Enter");
  await expect.poll(() => creations).toHaveLength(1);
});

test("opens the context picker and changes its searchable selection", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Research scope: Library" }).click();
  await expect(
    page.getByRole("heading", { name: "Add context" }),
  ).toBeVisible();
  await page.getByRole("switch", { name: "Entire library" }).click();
  await page.getByRole("searchbox").fill("RAG");
  await expect(
    page.getByRole("checkbox", { name: /RAG evaluation/ }),
  ).toBeVisible();
});

test("preserves compact sidebar density while collapsing", async ({ page }) => {
  await page.goto("/");
  const collapse = page.getByRole("button", { name: "Collapse sidebar" });
  const newChat = page.getByRole("link", { name: "New chat" });
  const newChatLabel = newChat.getByText("New chat", { exact: true });
  const account = page.getByRole("button", { name: "Open account menu" });
  const actorName = account.getByText(actor.display_name);
  const actorEmail = account.getByText(actor.email);
  const accountAvatar = account.locator("[data-account-avatar]");
  const conversation = page.getByText(homeConversations[0]!.title, {
    exact: true,
  });

  await expect(account.locator("svg")).toHaveCount(0);
  await expect(newChatLabel).toHaveCSS("font-size", "13px");
  await expect(actorName).toHaveCSS("font-size", "13px");
  await expect(conversation).toHaveCSS("font-size", "13px");
  await expect(actorEmail).toHaveCSS("font-size", "11px");
  await expect(account).toHaveCSS("height", "56px");
  await expect(accountAvatar).toHaveCSS("width", "40px");
  await expect(accountAvatar).toHaveCSS("height", "40px");
  expect(
    await actorEmail.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);

  const before = {
    newChat: await newChat.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
    account: await account.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
  };

  await collapse.click();
  await expect(
    page.getByRole("button", { name: "Expand sidebar" }),
  ).toBeVisible();
  await expect(page.locator("aside")).toHaveCSS("width", "64px");
  await expect(accountAvatar).toHaveCSS("width", "32px");
  await expect(accountAvatar).toHaveCSS("height", "32px");
  const after = {
    newChat: await newChat.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
    account: await account.evaluate((element) =>
      element.getBoundingClientRect().toJSON(),
    ),
  };

  expect(Math.abs(after.newChat.y - before.newChat.y)).toBeLessThan(1);
  expect(Math.abs(after.account.y - before.account.y)).toBeLessThan(1);
});

test("opens mobile navigation as a full-screen history hub", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();

  const dialog = page.getByRole("dialog");
  const panel = dialog.getByRole("complementary");
  const overlay = page.locator('[data-slot="sheet-overlay"]');
  await expect(dialog).toBeVisible();
  await expect(panel).toBeVisible();
  await expect(overlay).toBeVisible();
  await dialog.evaluate(async (element) => {
    await Promise.all(
      element.getAnimations().map((animation) => animation.finished),
    );
  });

  const metrics = await dialog.evaluate((element) => {
    const overlayElement = document.querySelector<HTMLElement>(
      '[data-slot="sheet-overlay"]',
    );
    const style = getComputedStyle(element);
    return {
      contentZ: Number(style.zIndex),
      overlayZ: Number(
        overlayElement ? getComputedStyle(overlayElement).zIndex : 0,
      ),
      width: element.getBoundingClientRect().width,
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
      viewportWidth: window.innerWidth,
    };
  });
  expect(Math.abs(metrics.width - metrics.viewportWidth)).toBeLessThanOrEqual(
    1,
  );
  expect(Math.abs(metrics.left)).toBeLessThanOrEqual(1);
  expect(Math.abs(metrics.right - metrics.viewportWidth)).toBeLessThanOrEqual(
    1,
  );
  await expect
    .poll(() =>
      panel.evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .not.toBe("rgba(0, 0, 0, 0)");
  expect(metrics.contentZ).toBeGreaterThan(metrics.overlayZ);
  const tools = dialog.getByTestId("mobile-navigation-tools");
  await expect(
    tools.getByRole("button", {
      name: "Search conversations and papers (⌘K)",
    }),
  ).toBeVisible();
  await expect(tools.getByRole("button", { name: "Settings" })).toBeVisible();
  await expect(tools.getByRole("link", { name: "New chat" })).toBeVisible();
  const toolsBox = await tools.boundingBox();
  expect(toolsBox?.y).toBeGreaterThan(400);
  expect((toolsBox?.y ?? 0) + (toolsBox?.height ?? 0)).toBeLessThanOrEqual(568);
});

test("fits the Home shell at 390px without horizontal scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  const primaryNavigation = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  const activeDestination = primaryNavigation.getByRole("link", {
    name: "Ask",
  });
  await expect(activeDestination).toHaveAttribute("aria-current", "page");
  await expect(
    activeDestination.locator("[data-selected-indicator]"),
  ).toBeVisible();
  await expect(
    primaryNavigation.getByRole("link", { name: "Library" }),
  ).toHaveAttribute("href", "/library");
  const dock = page.getByTestId("mobile-bottom-dock");
  await expect(dock.getByRole("textbox", { name: "Ask anything" })).toHaveCount(
    1,
  );
  await expect(dock.getByRole("navigation")).toHaveCount(1);
  await expect(
    dock.getByRole("button", { name: "Research scope: Library" }),
  ).toBeVisible();
  await expect(
    dock.getByRole("button", { name: "Reasoning strength: Standard" }),
  ).toHaveCount(0);
  expect(
    (await dock.locator("form").boundingBox())?.height,
  ).toBeLessThanOrEqual(72);
  const touchTargets = dock.locator("button:visible, a:visible");
  for (let index = 0; index < (await touchTargets.count()); index += 1) {
    const box = await touchTargets.nth(index).boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(48);
    expect(box?.width).toBeGreaterThanOrEqual(48);
  }

  const reasoningTrigger = page.getByRole("button", {
    name: "Reasoning strength: Standard",
  });
  await expect(reasoningTrigger).toBeVisible();
  await reasoningTrigger.click();
  await expect(page.getByRole("menuitemradio")).toHaveCount(2);
  await expect(page.getByText("Fast, balanced reasoning")).toHaveCount(0);
  await expect(page.getByText("More thorough reasoning")).toHaveCount(0);
  await expect(
    page.getByRole("menuitemradio", { name: /Standard/ }),
  ).toBeVisible();
  await expect(page.getByText("Choose model")).toHaveCount(0);
  await page.getByRole("menuitemradio", { name: /Deep/ }).click();
  await expect(
    page.getByRole("button", { name: "Reasoning strength: Deep" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Open navigation" }).click();
  const navigationHub = page.getByRole("dialog");
  await expect(
    navigationHub.getByRole("button", {
      name: "Search conversations and papers (⌘K)",
    }),
  ).toBeVisible();
  await expect(
    navigationHub.getByRole("link", { name: "New chat" }),
  ).toBeVisible();
  await navigationHub.getByRole("button", { name: "Close navigation" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("keeps the unified mobile Dock contained at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/");

  const dock = page.getByTestId("mobile-bottom-dock");
  const composer = dock.getByRole("textbox", { name: "Ask anything" });
  await expect(composer).toBeVisible();
  await expect(dock.getByTestId("mobile-tab-bar")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  const [dockBox, composerBox] = await Promise.all([
    dock.boundingBox(),
    composer.boundingBox(),
  ]);
  expect(dockBox?.y).toBeGreaterThan(0);
  expect(composerBox?.y).toBeGreaterThanOrEqual(dockBox?.y ?? 0);
});

test("keeps conversation scrolling independent from the mobile Dock", async ({
  page,
}) => {
  const conversation = homeConversations[0]!;
  const turns = Array.from({ length: 6 }, (_, index) => {
    const source = homeTurns[0]!;
    const turnId = `50000000-0000-4000-8000-00000000000${index + 1}`;
    const responseId = `40000000-0000-4000-8000-00000000000${index + 1}`;
    return {
      ...source,
      branch: { count: 1, index: 1 },
      depth: index + 1,
      id: turnId,
      parent_turn_id:
        index === 0
          ? null
          : `50000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      selected_response_id: responseId,
      suggestions: index === 5 ? source.suggestions : null,
      responses: source.responses.map((response) => ({
        ...response,
        id: responseId,
      })),
    };
  });
  await page.route(`${apiPattern}/conversations/${conversation.id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...conversation,
        paper_context: { kind: "library" },
        tool_permissions: [],
      }),
    }),
  );
  await page.route(
    `${apiPattern}/conversations/${conversation.id}/turns**`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: turns,
          next_cursor: null,
          path_revision: 1,
        }),
      }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/?conversation=${conversation.id}`);

  const main = page.locator("main");
  const dock = page.getByTestId("mobile-bottom-dock");
  await expect(
    page.getByRole("textbox", { name: "Ask a follow-up" }),
  ).toBeVisible();
  await expect(dock.getByTestId("mobile-tab-bar")).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const dockBefore = await dock.boundingBox();
  expect(dockBefore).not.toBeNull();
  expect(Math.round((dockBefore?.y ?? 0) + (dockBefore?.height ?? 0))).toBe(
    844,
  );
  expect(
    await main.evaluate(
      (element) => element.scrollHeight > element.clientHeight,
    ),
  ).toBe(true);
  const sourcePill = page.getByRole("button", { name: "1 source" }).last();
  await expect(sourcePill).toBeVisible();
  await sourcePill.click();
  const sourcePanel = page.getByRole("dialog", { name: "1 source" });
  await expect(sourcePanel).toBeVisible();
  await expect(
    sourcePanel.getByText(homePapers[0]!.document.title ?? "", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close sources" }).click();
  await expect(sourcePanel).toBeHidden();

  await main.evaluate((element) => element.scrollTo({ top: 0 }));
  const jumpToLatest = page.getByRole("button", {
    name: "Jump to the latest response",
  });
  await expect(jumpToLatest).toBeVisible();
  await expect
    .poll(async () => {
      const box = await dock.boundingBox();
      return {
        bottom: Math.round((box?.y ?? 0) + (box?.height ?? 0)),
        height: Math.round(box?.height ?? 0),
        keyboardOpen: await dock.getAttribute("data-keyboard-open"),
      };
    })
    .toEqual({
      bottom: 844,
      height: Math.round(dockBefore?.height ?? 0),
      keyboardOpen: null,
    });
  const [dockAfter, mainAfter] = await Promise.all([
    dock.boundingBox(),
    main.boundingBox(),
  ]);
  expect((mainAfter?.y ?? 0) + (mainAfter?.height ?? 0)).toBeLessThanOrEqual(
    dockAfter?.y ?? 0,
  );
  await jumpToLatest.click();
  await expect
    .poll(() =>
      main.evaluate(
        (element) =>
          element.scrollHeight - element.scrollTop - element.clientHeight,
      ),
    )
    .toBeLessThan(120);
  await expect(jumpToLatest).toBeHidden();
});

test("edits any prompt into a persistent branch and switches the full suffix", async ({
  page,
}) => {
  const conversation = homeConversations[0]!;
  const detail = {
    ...conversation,
    paper_context: { kind: "library" as const },
    tool_permissions: [],
  };
  const source = homeTurns[0]!;
  const rootId = source.id;
  const followUpId = "50000000-0000-4000-8000-000000000002";
  const followUpResponseId = "40000000-0000-4000-8000-000000000003";
  const originalQuestion = source.user_query;
  const followUpQuestion = "What evidence supports that contribution?";
  let editedTurnId: string | null = null;
  let editedTurn: ConversationTurn | null = null;
  let branchCreated = false;

  const originalPath = (): ConversationTurn[] => [
    {
      ...source,
      branch: {
        count: branchCreated ? 2 : 1,
        index: 1,
        next_turn_id: editedTurnId,
      },
    },
    {
      ...source,
      branch: { count: 1, index: 1 },
      depth: 2,
      id: followUpId,
      parent_turn_id: rootId,
      responses: source.responses.map((response) => ({
        ...response,
        id: followUpResponseId,
        content: "The evidence is reported in the evaluation section.",
      })),
      selected_response_id: followUpResponseId,
      suggestions: null,
      user_query: followUpQuestion,
    },
  ];
  let activePath: ConversationTurn[] = originalPath();

  await page.unroute(`${apiPattern}/conversations**`);
  await page.route(`${apiPattern}/conversations**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (
      pathname.endsWith(`/conversations/${conversation.id}/selected-branch`) &&
      request.method() === "PUT"
    ) {
      const body = request.postDataJSON() as { turn_id: string };
      if (body.turn_id === rootId) activePath = originalPath();
      else if (body.turn_id === editedTurnId && editedTurn)
        activePath = [editedTurn];
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: activePath,
          next_cursor: null,
          path_revision: 3,
        }),
      });
      return;
    }

    if (
      pathname.endsWith(
        `/conversations/${conversation.id}/turns/${rootId}/branches`,
      ) &&
      request.method() === "POST"
    ) {
      const body = request.postDataJSON() as {
        response_id: string;
        turn_id: string;
        user_query: string;
      };
      const rejectedEdits: Record<
        string,
        { code: string; message: string; status: number }
      > = {
        "Rejected edit stays here": {
          code: "conversation_response_in_progress",
          message: "Conversation is busy",
          status: 409,
        },
        "Rate limited edit stays here": {
          code: "rate_limit_exceeded",
          message: "AI request limit exceeded",
          status: 429,
        },
        "Capacity limited edit stays here": {
          code: "interactive_concurrency_exceeded",
          message: "AI request limit exceeded",
          status: 429,
        },
      };
      const rejection = rejectedEdits[body.user_query];
      if (rejection) {
        await route.fulfill({
          contentType: "application/json",
          status: rejection.status,
          body: JSON.stringify({
            code: rejection.code,
            message: rejection.message,
          }),
        });
        return;
      }
      editedTurnId = body.turn_id;
      branchCreated = true;
      const nextEditedTurn: ConversationTurn = {
        ...source,
        branch: {
          count: 2,
          index: 2,
          previous_turn_id: rootId,
        },
        id: body.turn_id,
        parent_turn_id: null,
        responses: [
          {
            artifacts: null,
            content: "The edited question follows a separate answer path.",
            duration_ms: 18_200,
            id: body.response_id,
            references: null,
            status: "completed",
            trace: null,
            variant_index: 1,
          },
        ],
        selected_response_id: body.response_id,
        suggestions: null,
        user_query: body.user_query,
      };
      editedTurn = nextEditedTurn;
      activePath = [nextEditedTurn];
      const events = [
        {
          type: "start",
          conversation_id: conversation.id,
          generation_kind: "branch",
          response_id: body.response_id,
          turn_id: body.turn_id,
          variant_index: 1,
        },
        { type: "response_ready", turn: nextEditedTurn },
        {
          type: "complete",
          response_id: body.response_id,
          turn_id: body.turn_id,
        },
      ];
      await route.fulfill({
        contentType: "text/event-stream",
        body: events
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(""),
      });
      return;
    }

    if (
      editedTurn &&
      editedTurnId &&
      pathname.endsWith(
        `/conversations/${conversation.id}/turns/${editedTurnId}/responses`,
      ) &&
      request.method() === "POST"
    ) {
      const body = request.postDataJSON() as { response_id: string };
      const completedResponse = {
        artifacts: null,
        content: "The failed branch completed after retry.",
        duration_ms: 2_900,
        id: body.response_id,
        references: null,
        status: "completed" as const,
        trace: null,
        variant_index: 2,
      };
      editedTurn = {
        ...editedTurn,
        responses: [...editedTurn.responses, completedResponse],
        selected_response_id: body.response_id,
      };
      activePath = [editedTurn];
      const events = [
        {
          type: "start",
          conversation_id: conversation.id,
          generation_kind: "retry",
          response_id: body.response_id,
          turn_id: editedTurnId,
          variant_index: 2,
        },
        { type: "response_ready", turn: editedTurn },
        {
          type: "complete",
          response_id: body.response_id,
          turn_id: editedTurnId,
        },
      ];
      await route.fulfill({
        contentType: "text/event-stream",
        body: events
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(""),
      });
      return;
    }

    if (
      pathname.endsWith(`/conversations/${conversation.id}/turns`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: activePath,
          next_cursor: null,
          path_revision: branchCreated ? 2 : 1,
        }),
      });
      return;
    }
    if (pathname.endsWith(`/conversations/${conversation.id}`)) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(detail),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [conversation], next_cursor: null }),
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/?conversation=${conversation.id}`);
  await expect(page.getByText(followUpQuestion, { exact: true })).toBeVisible();

  const composer = page.getByRole("textbox", { name: "Ask a follow-up" });
  const composerForm = composer.locator("xpath=ancestor::form");
  const userMessage = page
    .getByRole("article", { name: "Your message" })
    .first();
  const assistantMessage = page
    .getByRole("article", { name: "Assistant response" })
    .first();
  const assistantContent = assistantMessage
    .locator("[data-message-content]")
    .first();
  const [composerBox, userBox, assistantBox, assistantContentBox] =
    await Promise.all([
      composerForm.boundingBox(),
      userMessage.boundingBox(),
      assistantMessage.boundingBox(),
      assistantContent.boundingBox(),
    ]);
  expect(composerBox?.width).toBeCloseTo(832, 0);
  expect(
    Math.abs(
      (userBox?.x ?? 0) +
        (userBox?.width ?? 0) -
        ((composerBox?.x ?? 0) + (composerBox?.width ?? 0)),
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs((assistantBox?.x ?? 0) - (composerBox?.x ?? 0)),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs((assistantContentBox?.x ?? 0) - (composerBox?.x ?? 0)),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(
      (assistantContentBox?.x ?? 0) +
        (assistantContentBox?.width ?? 0) -
        ((composerBox?.x ?? 0) + (composerBox?.width ?? 0)),
    ),
  ).toBeLessThanOrEqual(1);

  const messageControls = userMessage.locator("[data-user-message-controls]");
  await expect(messageControls).toHaveCSS("opacity", "0");
  await userMessage.hover();
  await expect(messageControls).toHaveCSS("opacity", "1");
  await page.getByRole("button", { name: "Edit message" }).first().focus();
  await expect(messageControls).toHaveCSS("opacity", "1");

  await page.getByRole("button", { name: "Edit message" }).first().click();
  const editor = page.getByRole("textbox", { name: "Message text" });
  await editor.fill("Rejected edit stays here");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Your edit is still here/)).toBeVisible();
  await expect(editor).toHaveValue("Rejected edit stays here");
  expect(
    await editor.evaluate((element) => element === document.activeElement),
  ).toBe(true);

  for (const rejectedEdit of [
    "Rate limited edit stays here",
    "Capacity limited edit stays here",
  ]) {
    await editor.fill(rejectedEdit);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(/Your edit is still here/)).toBeVisible();
    await expect(editor).toHaveValue(rejectedEdit);
    expect(
      await editor.evaluate((element) => element === document.activeElement),
    ).toBe(true);
  }

  await editor.fill("What is the paper’s main systems contribution?");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(
    page.getByText("What is the paper’s main systems contribution?", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText(followUpQuestion, { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByLabel("Message 2 of 2")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Message 2 of 2")).toBeVisible();
  await expect(page.getByText(followUpQuestion, { exact: true })).toHaveCount(
    0,
  );

  await page
    .getByRole("button", { name: "Previous version of this message" })
    .click();
  await expect(page.getByText(originalQuestion, { exact: true })).toBeVisible();
  await expect(page.getByText(followUpQuestion, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Message 1 of 2")).toBeVisible();

  await page
    .getByRole("button", { name: "Next version of this message" })
    .click();
  await expect(page.getByLabel("Message 2 of 2")).toBeVisible();
  await expect(page.getByText(followUpQuestion, { exact: true })).toHaveCount(
    0,
  );

  const failedResponseId = editedTurn!.selected_response_id!;
  const persistedFailed: ConversationTurn = {
    ...editedTurn!,
    responses: editedTurn!.responses.map((response) =>
      response.id === failedResponseId
        ? {
            ...response,
            content: null,
            duration_ms: 6_200,
            status: "failed",
          }
        : response,
    ),
  };
  editedTurn = persistedFailed;
  activePath = [persistedFailed];
  await page.reload();
  await expect(page.getByText("Could not complete")).toBeVisible();
  await expect(page.getByRole("status")).toContainText("6s");
  await page.getByRole("button", { name: "Try another response" }).click();
  await expect(
    page.getByText("The failed branch completed after retry."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("keeps the Home composition contained on a 2560px desktop", async ({
  page,
}) => {
  await page.setViewportSize({ width: 2560, height: 1440 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("locale cookie selects the Home interface dictionary", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "scholens-locale",
      value: "zh-CN",
      url: "http://127.0.0.1:7300",
    },
  ]);
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(
    page.getByRole("heading", { name: "你正在研究什么？" }),
  ).toBeVisible();
});
