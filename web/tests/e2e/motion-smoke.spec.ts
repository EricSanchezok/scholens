import { expect, type Locator, type Page, test } from "@playwright/test";

import {
  homeConversations,
  homePapers,
  homeProjects,
  homeTurns,
} from "../../src/features/home/api/fixtures";
import { mockBillingUsage } from "./billing-fixture";

const apiPattern = "**/api/v1";
const readerDocument = homePapers[0]!.document;
const actor = {
  id: 7,
  email: "motion@scholens.test",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Motion Researcher",
  locale: "en",
};

async function railTransform(locator: Locator) {
  return locator.evaluate((element) => {
    const matrix = new DOMMatrixReadOnly(getComputedStyle(element).transform);
    return {
      scaleX: matrix.a,
      scaleY: matrix.d,
      skewX: matrix.c,
      skewY: matrix.b,
      translateX: matrix.e,
    };
  });
}

async function railClipRight(locator: Locator) {
  return locator.evaluate((element) => {
    const values = (getComputedStyle(element).clipPath.match(/[\d.]+/g) ?? [])
      .map(Number)
      .filter(Number.isFinite);
    return values.length > 1 ? values[1]! : (values[0] ?? 0);
  });
}

async function mockWorkspace(page: Page) {
  await mockBillingUsage(page);
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      body: JSON.stringify({
        access_token: "playwright-motion",
        actor,
        token_type: "bearer",
      }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      body: JSON.stringify({ items: homeConversations, next_cursor: null }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/library/papers`, (route) =>
    route.fulfill({
      body: JSON.stringify({ items: homePapers, next_cursor: null }),
      contentType: "application/json",
    }),
  );
  await page.route(`${apiPattern}/projects**`, (route) =>
    route.fulfill({
      body: JSON.stringify({ items: homeProjects, next_cursor: null }),
      contentType: "application/json",
    }),
  );
}

async function mockConversationSubmission(page: Page) {
  let submittedTurn: Record<string, unknown> | undefined;
  const conversation = {
    ...homeConversations[0]!,
    paper_context: { kind: "library" as const },
    tool_permissions: [],
  };
  await page.route(`${apiPattern}/conversations`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      body: JSON.stringify(conversation),
      contentType: "application/json",
      status: 201,
    });
  });
  await page.route(`${apiPattern}/conversations/${conversation.id}`, (route) =>
    route.fulfill({
      body: JSON.stringify(conversation),
      contentType: "application/json",
    }),
  );
  await page.route(
    `${apiPattern}/conversations/${conversation.id}/turns**`,
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          body: JSON.stringify({
            items: submittedTurn ? [submittedTurn] : [],
            next_cursor: null,
            path_revision: 1,
          }),
          contentType: "application/json",
        });
        return;
      }
      const request = route.request().postDataJSON() as {
        locale: string;
        reasoning_level: string;
        response_id: string;
        time_zone: string;
        turn_id: string;
        user_query: string;
      };
      const response = {
        artifacts: null,
        content: "The motion path is complete.",
        id: request.response_id,
        references: null,
        status: "completed",
        trace: null,
        variant_index: 1,
      };
      const turn = {
        branch: { count: 1, index: 1 },
        contexts: [],
        depth: 1,
        id: request.turn_id,
        locale: request.locale,
        paper_context: conversation.paper_context,
        parent_turn_id: null,
        reasoning_level: request.reasoning_level,
        responses: [response],
        selected_response_id: request.response_id,
        suggestions: null,
        time_zone: request.time_zone,
        user_query: request.user_query,
      };
      submittedTurn = turn;
      const events = [
        {
          conversation_id: conversation.id,
          generation_kind: "initial",
          response_id: request.response_id,
          turn_id: request.turn_id,
          type: "start",
          variant_index: 1,
        },
        { response_id: request.response_id, turn, type: "response_ready" },
        {
          response_id: request.response_id,
          turn_id: request.turn_id,
          type: "complete",
        },
      ];
      await route.fulfill({
        body: events
          .map(
            (event) =>
              `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
          )
          .join(""),
        contentType: "text/event-stream",
      });
    },
  );
}

async function mockReaderMotion(page: Page) {
  await page.route(
    `${apiPattern}/papers/${readerDocument.document_id}`,
    (route) =>
      route.fulfill({
        body: JSON.stringify(readerDocument),
        contentType: "application/json",
      }),
  );
  await page.route(
    `${apiPattern}/papers/${readerDocument.document_id}/projects`,
    (route) =>
      route.fulfill({
        body: JSON.stringify({ items: [], next_cursor: null }),
        contentType: "application/json",
      }),
  );
  await page.route(`${apiPattern}/me/translation-preferences`, (route) =>
    route.fulfill({
      body: JSON.stringify({
        auto_translate_selection: true,
        custom_instructions: null,
        full_translation_display: "bilingual",
        show_translation_marker: true,
        source_language: "auto",
        target_language: "zh-CN",
        translate_references: false,
      }),
      contentType: "application/json",
    }),
  );
  await page.route(
    `${apiPattern}/papers/${readerDocument.document_id}/reflow`,
    (route) =>
      route.fulfill({
        body: JSON.stringify({
          assets: [],
          blocks: [
            {
              asset_id: null,
              group_id: null,
              heading_level: 1,
              id: "motion-title",
              index: 0,
              kind: "title",
              presentation_status: "verbatim",
              render_markdown: "# Motion-safe academic reading",
              source_spans: [
                {
                  page_number: 1,
                  source_rect: {
                    height: 0.08,
                    width: 0.72,
                    x: 0.14,
                    y: 0.12,
                  },
                  source_text: "Motion-safe academic reading",
                },
              ],
            },
            {
              asset_id: null,
              group_id: null,
              heading_level: 2,
              id: "motion-method",
              index: 1,
              kind: "heading",
              presentation_status: "verbatim",
              render_markdown: "## 1 Method",
              source_spans: [
                {
                  page_number: 2,
                  source_rect: {
                    height: 0.05,
                    width: 0.72,
                    x: 0.14,
                    y: 0.12,
                  },
                  source_text: "1 Method",
                },
              ],
            },
          ],
          document_id: readerDocument.document_id,
          error_code: null,
          job_id: "70000000-0000-4000-8000-000000000001",
          parser_revision: "motion-smoke-v1",
          pipeline_revision: "motion-smoke-v1",
          status: "completed",
          updated_at: "2026-08-16T00:00:00Z",
          warnings: [],
        }),
        contentType: "application/json",
      }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockWorkspace(page);
});

test("honors system reduced motion before hydration", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "system");
  });
  await mockConversationSubmission(page);

  await page.goto("/");
  const root = page.locator("html");
  expect(
    await root.evaluate((element) =>
      getComputedStyle(element)
        .getPropertyValue("--motion-duration-standard")
        .trim(),
    ),
  ).toMatch(/^(?:220ms|0?\.22s)$/);
  await expect(root).toHaveAttribute("data-motion-preference", "system");
  await expect(root).toHaveAttribute("data-motion", "reduced");

  await page.getByRole("button", { name: "Open account menu" }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(menu).toHaveCSS("animation-name", "none");
  await page.keyboard.press("Escape");

  await page.evaluate(() => {
    const samples: string[] = [];
    Object.assign(window, { __systemReducedRuntimeTransforms: samples });
    const observer = new MutationObserver(() => {
      const surface = document.querySelector<HTMLElement>(
        '[data-home-surface="conversation"]',
      );
      if (surface) samples.push(getComputedStyle(surface).transform);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  const composer = page.getByRole("textbox", { name: "Ask anything" });
  await composer.fill("Verify system reduced motion at runtime");
  await page.getByRole("button", { name: "Ask Scholens" }).click();
  const conversationSurface = page.locator(
    '[data-home-surface="conversation"]',
  );
  await expect(conversationSurface).toBeVisible();
  await expect(conversationSurface).toHaveCSS("transform", "none");
  const runtimeTransforms = await page.evaluate(
    () =>
      (
        window as typeof window & {
          __systemReducedRuntimeTransforms?: string[];
        }
      ).__systemReducedRuntimeTransforms ?? [],
  );
  expect(runtimeTransforms.length).toBeGreaterThan(0);
  expect(runtimeTransforms).toEqual(runtimeTransforms.map(() => "none"));
});

test("lets an explicit full-motion preference override the OS setting", async ({
  browserName,
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "full");
  });

  await page.goto("/");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-motion-preference", "full");
  await expect(root).toHaveAttribute("data-motion", "full");

  await page.getByRole("button", { name: "Open account menu" }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(menu).toHaveCSS("animation-name", "motion-popup-in");

  await page.keyboard.press("Escape");
  const composer = page.getByRole("textbox", { name: "Ask anything" });
  const composerBox = await composer.boundingBox();
  expect(composerBox).not.toBeNull();
  await page.mouse.move(
    composerBox!.x + composerBox!.width / 2,
    composerBox!.y + composerBox!.height / 2,
  );
  await page.mouse.down();
  await expect(composer).toHaveCSS("transform", "none");
  await page.mouse.up();

  const interactiveRow = page
    .locator(".motion-control.group\\/interactive-row")
    .first();
  const rowBox = await interactiveRow.boundingBox();
  expect(rowBox).not.toBeNull();
  await page.mouse.move(
    rowBox!.x + rowBox!.width / 2,
    rowBox!.y + rowBox!.height / 2,
  );
  await page.mouse.down();
  await expect(interactiveRow).toHaveCSS("transform", "none");
  await page.mouse.move(1, 1);
  await page.mouse.up();

  const collapse = page.getByRole("button", { name: "Collapse sidebar" });
  const collapseBox = await collapse.boundingBox();
  expect(collapseBox).not.toBeNull();
  await page.mouse.move(
    collapseBox!.x + collapseBox!.width / 2,
    collapseBox!.y + collapseBox!.height / 2,
  );
  await page.mouse.down();
  if (browserName === "chromium") {
    await expect
      .poll(() =>
        collapse.evaluate((element) => getComputedStyle(element).transform),
      )
      .not.toBe("none");
  }
  await page.mouse.up();
  const sidebar = page.locator('aside[aria-label="Workspace sidebar"]');
  const railContent = page.locator("[data-motion-rail-content]");
  const railChrome = page.locator(".motion-rail-chrome");
  const workspace = page.locator("[data-workspace-shell]");
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect
    .poll(async () => {
      const [transform, clipRight] = await Promise.all([
        railTransform(railContent),
        railClipRight(railChrome),
      ]);
      return (
        transform.translateX > 0 &&
        transform.translateX < 200 &&
        clipRight > 0 &&
        clipRight < 200
      );
    })
    .toBe(true);
  const collapseFrame = await railTransform(railContent);
  expect(collapseFrame.scaleX).toBeCloseTo(1, 4);
  expect(collapseFrame.scaleY).toBeCloseTo(1, 4);
  expect(collapseFrame.skewX).toBeCloseTo(0, 4);
  expect(collapseFrame.skewY).toBeCloseTo(0, 4);
  expect(collapseFrame.translateX).toBeGreaterThan(0);
  expect(collapseFrame.translateX).toBeLessThan(200);
  await expect(sidebar.getByText("Scholens", { exact: true })).toHaveCSS(
    "transform",
    "none",
  );
  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
  ).toHaveCSS("transform", "none");
  const expandSidebar = page.getByRole("button", { name: "Expand sidebar" });
  await expect(expandSidebar).toBeVisible();
  await expandSidebar.click();
  await expect(sidebar).toHaveCSS("width", "288px");
  await expect
    .poll(async () => {
      const [transform, clipRight] = await Promise.all([
        railTransform(railContent),
        railClipRight(railChrome),
      ]);
      return (
        transform.translateX < 0 &&
        transform.translateX > -200 &&
        clipRight > 0 &&
        clipRight < 200
      );
    })
    .toBe(true);
  const interruptionFrame = await railTransform(railContent);
  expect(interruptionFrame.scaleX).toBeCloseTo(1, 4);
  expect(interruptionFrame.scaleY).toBeCloseTo(1, 4);
  expect(interruptionFrame.skewX).toBeCloseTo(0, 4);
  expect(interruptionFrame.skewY).toBeCloseTo(0, 4);
  expect(interruptionFrame.translateX).toBeLessThan(0);
  expect(interruptionFrame.translateX).toBeGreaterThan(-200);
  await expect(railContent).toHaveCSS("transform", "none");
  await expect.poll(() => railClipRight(railChrome)).toBeCloseTo(0, 4);
  expect(
    await railContent.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
  expect(
    await railChrome.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
  await expect(workspace).toHaveCSS("overflow", "hidden");
  expect(
    await workspace.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);

  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect(railContent).toHaveCSS("transform", "none");
  await expect.poll(() => railClipRight(railChrome)).toBeCloseTo(224, 4);
  expect(
    await railContent.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
  expect(
    await railChrome.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);

  const newChat = page.getByRole("link", { name: "New chat" });
  await newChat.hover();
  const tooltip = page.getByRole("tooltip", { name: "New chat" });
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveCSS("animation-name", "motion-popup-in");
});

test("cancels an active rail FLIP when system motion becomes reduced", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "system");
  });
  await page.goto("/");

  const root = page.locator("html");
  const sidebar = page.locator('aside[aria-label="Workspace sidebar"]');
  const railContent = page.locator("[data-motion-rail-content]");
  const railChrome = page.locator(".motion-rail-chrome");
  await expect(root).toHaveAttribute("data-motion", "full");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect
    .poll(async () => {
      const [contentAnimations, chromeAnimations] = await Promise.all([
        railContent.evaluate((element) => element.getAnimations().length),
        railChrome.evaluate((element) => element.getAnimations().length),
      ]);
      return contentAnimations + chromeAnimations;
    })
    .toBeGreaterThan(0);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(root).toHaveAttribute("data-motion", "reduced");
  await expect(railContent).toHaveCSS("transform", "none");
  await expect.poll(() => railClipRight(railChrome)).toBeCloseTo(224, 4);
  expect(
    await railContent.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
  expect(
    await railChrome.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
});

test("commits the Home-to-conversation swap without reduced spatial interpolation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "reduced");
  });
  await mockConversationSubmission(page);
  await page.goto("/");

  const reducedRailContent = page.locator("[data-motion-rail-content]");
  const reducedRailChrome = page.locator(".motion-rail-chrome");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(
    page.getByRole("button", { name: "Expand sidebar" }),
  ).toBeVisible();
  await expect(page.locator('aside[aria-label="Workspace sidebar"]')).toHaveCSS(
    "width",
    "64px",
  );
  await expect(reducedRailContent).toHaveCSS("transform", "none");
  await expect.poll(() => railClipRight(reducedRailChrome)).toBeCloseTo(224, 4);
  expect(
    await reducedRailContent.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);
  expect(
    await reducedRailChrome.evaluate((element) => element.getAnimations()),
  ).toHaveLength(0);

  await expect(
    page.getByRole("heading", { name: "What are you working on?" }),
  ).toBeVisible();
  const composer = page.getByRole("textbox", { name: "Ask anything" });
  await composer.fill("Trace motion through the workspace");
  await page.getByRole("button", { name: "Ask Scholens" }).click();

  await expect(page.locator('[data-home-surface="dashboard"]')).toHaveCount(0);
  const conversationSurface = page.locator(
    '[data-home-surface="conversation"]',
  );
  await expect(conversationSurface).toBeVisible();
  await expect(conversationSurface).toHaveCSS("transform", "none");
  await expect(
    page.getByText("Trace motion through the workspace", { exact: true }),
  ).toBeVisible();
  const followUp = page.getByRole("textbox", { name: "Ask a follow-up" });
  await expect(followUp).toBeEnabled();
  await followUp.focus();
  await expect(followUp).toBeFocused();
});

test("discloses Reader outline and context panels without reduced spatial interpolation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "reduced");
  });
  await mockReaderMotion(page);
  await page.goto(`/reader/${readerDocument.document_id}?view=reflow`);

  await expect(
    page.getByRole("heading", { name: "Motion-safe academic reading" }),
  ).toBeVisible();
  const showOutline = page.getByRole("button", {
    name: "Show document outline",
  });
  await expect(showOutline).toBeEnabled();
  await showOutline.focus();
  await page.keyboard.press("Enter");
  const outline = page.getByRole("navigation", { name: "Document outline" });
  await expect(outline).toBeVisible();
  const hideOutline = page.getByRole("button", {
    name: "Hide document outline",
  });
  await expect(hideOutline).toHaveAttribute("aria-pressed", "true");
  await expect(hideOutline).toBeFocused();
  await expect(outline.locator("xpath=..")).toHaveCSS("transform", "none");
  await hideOutline.click();
  await expect(outline).toHaveCount(0);

  const openPanel = page.getByRole("button", { name: "Open context panel" });
  await openPanel.focus();
  await page.keyboard.press("Enter");
  const contextPanel = page.getByRole("complementary", {
    name: "Reader context",
  });
  await expect(contextPanel).toBeVisible();
  const closePanel = page.getByRole("button", { name: "Close context panel" });
  await expect(closePanel).toBeFocused();
  await expect(contextPanel.locator("xpath=..")).toHaveCSS("transform", "none");

  const details = contextPanel.getByRole("button", { name: "Details" });
  await details.focus();
  await page.keyboard.press("Enter");
  await expect(details).toHaveAttribute("aria-current", "page");
  await expect(details).toBeFocused();
  const detailsContent = contextPanel.locator(
    '[data-reader-panel-content="details"]',
  );
  await expect(detailsContent).toBeAttached();
  await expect(detailsContent).toHaveCSS("transform", "none");
  await expect(contextPanel.getByText("File", { exact: true })).toBeVisible();
});

test("uses the explicit reduced policy for one-step conversation scrolling", async ({
  page,
}) => {
  const conversation = homeConversations[0]!;
  const turns = Array.from({ length: 6 }, (_, index) => {
    const source = homeTurns[0]!;
    const suffix = String(index + 1).padStart(12, "0");
    const previousSuffix = String(index).padStart(12, "0");
    const turnId = `50000000-0000-4000-8000-${suffix}`;
    const responseId = `40000000-0000-4000-8000-${suffix}`;
    return {
      ...source,
      branch: { count: 1, index: 1 },
      depth: index + 1,
      id: turnId,
      parent_turn_id:
        index === 0 ? null : `50000000-0000-4000-8000-${previousSuffix}`,
      selected_response_id: responseId,
      suggestions: index === 5 ? source.suggestions : null,
      responses: source.responses.map((response) => ({
        ...response,
        id: responseId,
      })),
    };
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-motion", "reduced");
  });
  await page.route(`${apiPattern}/conversations/${conversation.id}`, (route) =>
    route.fulfill({
      body: JSON.stringify({
        ...conversation,
        paper_context: { kind: "library" },
        tool_permissions: [],
      }),
      contentType: "application/json",
    }),
  );
  await page.route(
    `${apiPattern}/conversations/${conversation.id}/turns**`,
    (route) =>
      route.fulfill({
        body: JSON.stringify({
          items: turns,
          next_cursor: null,
          path_revision: 1,
        }),
        contentType: "application/json",
      }),
  );
  await page.goto("/");

  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-motion-preference", "reduced");
  await expect(root).toHaveAttribute("data-motion", "reduced");

  const reducedControl = page.locator(".motion-control").first();
  const reducedIcon = page.locator(".motion-icon").first();
  await expect(reducedControl).toHaveCSS(
    "transition-property",
    "color, background-color, border-color, opacity",
  );
  await expect(reducedIcon).toHaveCSS("transition-duration", "0s");
  await page.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("menuitem", { name: "Usage" }).click();
  const reducedProgress = page.locator(".motion-progress").first();
  await expect(reducedProgress).toBeVisible();
  await expect(reducedProgress).toHaveCSS("transition-duration", "0s");
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(page).toHaveURL("/");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/?conversation=${conversation.id}`);
  await expect(root).toHaveAttribute("data-motion", "reduced");
  const main = page.locator("main");
  await expect
    .poll(() =>
      main.evaluate((element) => element.scrollHeight > element.clientHeight),
    )
    .toBe(true);
  await main.evaluate((element) => element.scrollTo({ top: 0 }));
  const jumpToLatest = page.getByRole("button", {
    name: "Jump to the latest response",
  });
  await expect(jumpToLatest).toBeVisible();

  await main.evaluate((element) => {
    let prototype: object | null = element;
    let descriptor: PropertyDescriptor | undefined;
    while (prototype && !descriptor) {
      descriptor = Object.getOwnPropertyDescriptor(prototype, "scrollTop");
      prototype = Object.getPrototypeOf(prototype) as object | null;
    }
    if (!descriptor?.get || !descriptor.set) {
      throw new Error("Native scrollTop accessors are unavailable");
    }
    const nativeGet = descriptor.get;
    const nativeSet = descriptor.set;
    const writes: number[] = [];
    const observed = element as HTMLElement & {
      motionScrollWrites?: number[];
    };
    observed.motionScrollWrites = writes;
    Object.defineProperty(element, "scrollTop", {
      configurable: true,
      get: () => nativeGet.call(element) as number,
      set: (value: number) => {
        writes.push(value);
        nativeSet.call(element, value);
      },
    });
  });

  await jumpToLatest.click();
  await expect(jumpToLatest).toBeHidden();
  const result = await main.evaluate((element) => {
    const observed = element as HTMLElement & {
      motionScrollWrites?: number[];
    };
    return {
      scrollTop: element.scrollTop,
      target: element.scrollHeight - element.clientHeight,
      writes: observed.motionScrollWrites ?? [],
    };
  });
  expect(result.writes).toHaveLength(1);
  expect(result.writes[0]).toBeCloseTo(result.target, 5);
  expect(result.scrollTop).toBeCloseTo(result.target, 5);
});
