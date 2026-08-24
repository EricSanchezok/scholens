import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { getRouter } from "@storybook/nextjs-vite/navigation.mock";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { delay, http, HttpResponse } from "msw";
import * as React from "react";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { billingHandlers } from "../../../.storybook/msw/billing-handlers";
import { Providers } from "@/app/providers";
import type { components } from "@/lib/api/generated/schema";
import { resetRefreshForTests } from "@/lib/api";
import { WorkspaceShell } from "./workspace-shell";

type Conversation = components["schemas"]["ConversationSummaryResponse"];

const conversations: Conversation[] = [
  {
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: false,
      move: true,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    id: "76000000-0000-4000-8000-000000000001",
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: null,
    scope_label: null,
    scope_type: "global",
    title: "Review retrieval methods across multimodal research archives",
    updated_at: "2026-08-11T08:00:00Z",
  },
];

const longHistoryConversations: Conversation[] = Array.from(
  { length: 65 },
  (_, index) => ({
    ...conversations[0]!,
    id: `76000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    pinned_at:
      index < 4
        ? new Date(Date.now() - index * 86_400_000).toISOString()
        : null,
    scope_label: index % 3 === 0 ? "CWM Agent survey" : "Memory systems",
    title: `Conversation ${index + 1}: a descriptive research question`,
    updated_at: new Date(Date.now() - index * 86_400_000).toISOString(),
  }),
);

const longIdentityActor = {
  ...actor,
  display_name: "EricSanchez",
  email: "niexiaohangeric@163.com",
};

const conversationListHandler = http.get(
  "http://127.0.0.1:7301/api/v1/conversations",
  () => HttpResponse.json({ items: conversations, next_cursor: null }),
);

async function findConversationRow(
  canvasElement: HTMLElement,
  conversationId = conversations[0]!.id,
) {
  await waitFor(() =>
    expect(
      canvasElement.querySelector(
        `[data-conversation-row="${conversationId}"]`,
      ),
    ).not.toBeNull(),
  );
  return canvasElement.querySelector<HTMLElement>(
    `[data-conversation-row="${conversationId}"]`,
  )!;
}

function ShellStory({
  activeDestination = "library",
  storyActor = actor,
}: {
  activeDestination?: "ask" | "library" | "projects" | "me";
  storyActor?: typeof actor;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  return (
    <WorkspaceShell
      activeDestination={activeDestination}
      actor={storyActor}
      collapsed={collapsed}
      mobileHeaderCenter={
        <span className="block truncate text-base font-semibold">Library</span>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={async () => undefined}
      signingOut={false}
    >
      <div className="mx-auto w-full max-w-4xl p-6 lg:p-10">
        <h1 className="text-3xl font-semibold">Workspace content</h1>
        <p className="text-secondary mt-2 text-sm">
          Product features own this region without owning navigation layout.
        </p>
      </div>
    </WorkspaceShell>
  );
}

const meta = {
  title: "Features/Workspace Shell",
  component: ShellStory,
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
  parameters: {
    layout: "fullscreen",
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        conversationListHandler,
      ],
    },
    nextjs: { appDirectory: true },
  },
  loaders: [
    async () => {
      resetRefreshForTests();
      getRouter().replace.mockClear();
      return {};
    },
  ],
} satisfies Meta<typeof ShellStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DesktopExpanded: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("complementary")).toBeVisible();
    const search = canvas.getByRole("button", {
      name: "Search conversations and papers (⌘K)",
    });
    await expect(search).toBeVisible();
    await expect(search).toHaveClass("size-8");
    await expect(
      within(
        canvas.getByRole("navigation", { name: "Open navigation" }),
      ).queryByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    ).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Library" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const navigation = within(
      canvas.getByRole("navigation", { name: "Open navigation" }),
    );
    for (const label of ["New chat", "Library", "Projects"]) {
      await expect(navigation.getByText(label)).not.toHaveClass(
        "settled-content-enter",
      );
    }
  },
};

export const DesktopLongContent: Story = {
  args: { storyActor: longIdentityActor },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const account = canvas.getByRole("button", { name: "Open account menu" });
    const name = within(account).getByText(longIdentityActor.display_name);
    const email = within(account).getByText(longIdentityActor.email);
    const conversation = await canvas.findByText(conversations[0]!.title);
    const newChat = within(
      canvas.getByRole("link", { name: "New chat" }),
    ).getByText("New chat");

    await expect(newChat).toHaveStyle({ fontSize: "13px" });
    await expect(name).toHaveStyle({ fontSize: "13px" });
    await expect(conversation).toHaveStyle({ fontSize: "13px" });
    await expect(email).toHaveStyle({ fontSize: "11px" });
    await expect(email).toBeVisible();
    await expect(email.scrollWidth).toBeLessThanOrEqual(email.clientWidth);
  },
};

export const DesktopUltrawide: Story = {
  globals: { viewport: { value: "ultrawide", isRotated: false } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("complementary")).toHaveStyle({
      width: "320px",
    });
  },
};

export const UnifiedSearchKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", {
      name: "Search conversations and papers (⌘K)",
    });
    trigger.focus();
    await userEvent.keyboard("{Meta>}k{/Meta}");
    const body = within(document.body);
    const search = await body.findByRole("searchbox", {
      name: "Search conversations or papers",
    });
    await userEvent.type(search, "😀");
    await expect(body.getByText("Recent conversations")).toBeVisible();
    await userEvent.clear(search);
    await userEvent.type(search, "memory");
    const result = await body.findByRole("link", {
      name: /Comparing memory retrieval strategies/,
    });
    search.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(result).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        body.queryByRole("dialog", { name: "Search Scholens" }),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  },
};

export const UnifiedSearchLoading: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        conversationListHandler,
        http.post(
          "http://127.0.0.1:7301/api/v1/search/conversations",
          async () => {
            await delay("infinite");
            return HttpResponse.json({
              items: [],
              next_cursor: null,
              total: 0,
            });
          },
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    );
    const body = within(document.body);
    await userEvent.type(
      await body.findByRole("searchbox", {
        name: "Search conversations or papers",
      }),
      "memory",
    );
    await expect(
      await body.findByRole("status", { name: "Searching conversations" }),
    ).toBeVisible();
  },
};

export const UnifiedSearchError: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        conversationListHandler,
        http.post("http://127.0.0.1:7301/api/v1/search/conversations", () =>
          HttpResponse.json({ detail: "Unavailable" }, { status: 503 }),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    );
    const body = within(document.body);
    await userEvent.type(
      await body.findByRole("searchbox", {
        name: "Search conversations or papers",
      }),
      "memory",
    );
    await expect(
      await body.findByText("Search is unavailable", {}, { timeout: 2500 }),
    ).toBeVisible();
  },
};

export const UnifiedSearchIme: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    );
    const body = within(document.body);
    const search = await body.findByRole("searchbox", {
      name: "Search conversations or papers",
    });
    await fireEvent.compositionStart(search, { data: "记" });
    await fireEvent.change(search, { target: { value: "记忆" } });
    await new Promise((resolve) => window.setTimeout(resolve, 320));
    await expect(body.getByText("Recent conversations")).toBeVisible();
    await fireEvent.compositionEnd(search, { data: "记忆" });
    await expect(
      await body.findByRole("link", {
        name: /Comparing memory retrieval strategies/,
      }),
    ).toBeVisible();
  },
};

export const LongPaginatedHistory: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        http.get(
          "http://127.0.0.1:7301/api/v1/conversations",
          ({ request }) => {
            const cursor = new URL(request.url).searchParams.get("cursor");
            const start = cursor ? 50 : 0;
            return HttpResponse.json({
              items: longHistoryConversations.slice(start, start + 50),
              next_cursor:
                start + 50 < longHistoryConversations.length
                  ? "history-page-two"
                  : null,
            });
          },
        ),
      ],
    },
  },
};

export const DesktopCollapsed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sidebar = canvas.getByRole("complementary");
    const railChrome = canvasElement.querySelector<HTMLElement>(
      ".motion-rail-chrome",
    )!;
    const railContent = canvasElement.querySelector<HTMLElement>(
      "[data-motion-rail-content]",
    )!;
    await userEvent.click(
      canvas.getByRole("button", { name: "Collapse sidebar" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Expand sidebar" }),
    ).toBeVisible();
    await expect(
      within(
        canvas.getByRole("navigation", { name: "Open navigation" }),
      ).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    ).toBeVisible();
    await expect(sidebar).toHaveStyle({ width: "64px" });
    await expect(getComputedStyle(sidebar).transitionProperty).not.toContain(
      "width",
    );
    await expect(getComputedStyle(railContent).transform).toBe("none");
    await expect(getComputedStyle(railChrome).clipPath).toContain("224px");
    await expect(railContent.getAnimations()).toHaveLength(0);
    await expect(railChrome.getAnimations()).toHaveLength(0);

    await userEvent.click(
      canvas.getByRole("button", { name: "Expand sidebar" }),
    );
    const navigation = within(
      canvas.getByRole("navigation", { name: "Open navigation" }),
    );
    for (const label of ["New chat", "Library", "Projects"]) {
      await expect(navigation.getByText(label)).toHaveClass(
        "settled-content-enter",
      );
    }
  },
};

const conversationMutationHandlers = [
  conversationListHandler,
  http.patch(
    "http://127.0.0.1:7301/api/v1/conversations/:conversationId",
    async ({ request }) => {
      const body = (await request.json()) as {
        pinned?: boolean;
        title?: string;
      };
      return HttpResponse.json({
        ...conversations[0],
        pinned_at: body.pinned ? "2026-08-15T12:00:00Z" : null,
        title: body.title ?? conversations[0]!.title,
      });
    },
  ),
  http.delete(
    "http://127.0.0.1:7301/api/v1/conversations/:conversationId",
    () => new HttpResponse(null, { status: 204 }),
  ),
];

export const ConversationActions: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        ...conversationMutationHandlers,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = await findConversationRow(canvasElement);
    await userEvent.hover(row);
    const trigger = canvas.getByRole("button", {
      name: `Open actions for ${conversations[0]!.title}`,
    });
    trigger.focus();
    await expect(trigger).toHaveFocus();

    await userEvent.click(trigger);
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Rename" }),
    );
    const input = canvas.getByRole("textbox", { name: "Conversation title" });
    await userEvent.clear(input);
    await userEvent.type(input, "思维链压缩方法");
    await fireEvent.compositionStart(input);
    await fireEvent.keyDown(input, {
      isComposing: true,
      key: "Enter",
      keyCode: 229,
    });
    await expect(input).toBeVisible();
    await fireEvent.compositionEnd(input, { data: "法" });
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        canvas.queryByRole("textbox", { name: "Conversation title" }),
      ).not.toBeInTheDocument(),
    );

    await userEvent.hover(row);
    const restoredTrigger = canvas.getByRole("button", {
      name: `Open actions for ${conversations[0]!.title}`,
    });
    await waitFor(() => expect(restoredTrigger).toHaveFocus());
    await userEvent.click(restoredTrigger);
    await userEvent.click(await body.findByRole("menuitem", { name: "Pin" }));
  },
};

export const ConversationDelete: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        ...conversationMutationHandlers,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = await findConversationRow(canvasElement);
    await userEvent.hover(row);
    await userEvent.click(
      canvas.getByRole("button", {
        name: `Open actions for ${conversations[0]!.title}`,
      }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Delete" }),
    );
    const dialog = await body.findByRole("alertdialog");
    await expect(dialog).toHaveTextContent(conversations[0]!.title);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(body.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
  },
};

export const ConversationRenameFailure: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        conversationListHandler,
        http.patch(
          "http://127.0.0.1:7301/api/v1/conversations/:conversationId",
          () => HttpResponse.json({ detail: "Rename failed" }, { status: 503 }),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = await findConversationRow(canvasElement);
    await userEvent.hover(row);
    await userEvent.click(
      canvas.getByRole("button", { name: /Open actions for/ }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Rename" }),
    );
    const input = canvas.getByRole("textbox", { name: "Conversation title" });
    await userEvent.clear(input);
    await userEvent.type(input, "A title that the server rejects{Enter}");
    await expect(input).toBeVisible();
    await expect(
      await body.findByText("Conversation could not be updated. Try again."),
    ).toBeVisible();
    await waitFor(() => expect(input).toBeEnabled());
    await waitFor(() => expect(input).toHaveFocus());
  },
};

export const ConversationDeleteFailure: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        conversationListHandler,
        http.delete(
          "http://127.0.0.1:7301/api/v1/conversations/:conversationId",
          () => HttpResponse.json({ detail: "Delete failed" }, { status: 503 }),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = await findConversationRow(canvasElement);
    await userEvent.hover(row);
    await userEvent.click(
      canvas.getByRole("button", { name: /Open actions for/ }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Delete" }),
    );
    const dialog = await body.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Delete" }),
    );
    await expect(dialog).toBeVisible();
    await expect(row).toBeInTheDocument();
    await expect(
      await body.findByText("Conversation could not be updated. Try again."),
    ).toBeVisible();
  },
};

export const ConversationPermissions: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        http.get("http://127.0.0.1:7301/api/v1/conversations", () =>
          HttpResponse.json({
            items: [
              {
                ...conversations[0]!,
                capabilities: {
                  ...conversations[0]!.capabilities,
                  delete: false,
                  pin: false,
                  rename: false,
                },
              },
            ],
            next_cursor: null,
          }),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = await findConversationRow(canvasElement);
    await userEvent.hover(row);
    await userEvent.click(
      canvas.getByRole("button", { name: /Open actions for/ }),
    );
    const menu = await body.findByRole("menu");
    await expect(within(menu).getAllByRole("menuitem")).toHaveLength(1);
    await expect(
      within(menu).getByRole("menuitem", { name: "Open in new tab" }),
    ).toBeVisible();
  },
};

export const AccountMenuUsage: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const trigger = canvas.getByRole("button", { name: "Open account menu" });

    await userEvent.click(trigger);
    const menu = await body.findByRole("menu");
    await expect(await within(menu).findByText("Researcher")).toBeVisible();
    await expect(await within(menu).findByText("24M / 100M")).toBeVisible();
    await expect(
      await within(menu).findByText("Credits reset on Aug 17, 2026"),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "Repository" }),
    ).toHaveAttribute("href", "https://github.com/EricSanchezok/scholens");
    await expect(
      within(menu).getByRole("menuitem", { name: "Repository" }),
    ).toHaveAttribute("target", "_blank");
    await expect(
      within(menu).getByRole("menuitem", { name: "Documentation" }),
    ).toHaveAttribute("href", "/docs");
    await expect(
      within(menu).getByRole("menuitem", { name: "Documentation" }),
    ).toHaveAttribute("target", "_blank");

    await userEvent.click(
      within(menu).getByRole("menuitem", { name: "Settings" }),
    );
    await expect(getRouter().replace).toHaveBeenCalledWith(
      "/?settings=general",
      { scroll: false },
    );

    getRouter().replace.mockClear();
    await userEvent.click(trigger);
    await userEvent.click(
      within(await body.findByRole("menu")).getByRole("menuitem", {
        name: "Account",
      }),
    );
    await expect(getRouter().replace).toHaveBeenCalledWith(
      "/?settings=account",
      { scroll: false },
    );

    getRouter().replace.mockClear();
    await userEvent.click(trigger);
    await userEvent.click(
      within(await body.findByRole("menu")).getByRole("menuitem", {
        name: "Usage",
      }),
    );
    await expect(getRouter().replace).toHaveBeenCalledWith("/?settings=usage", {
      scroll: false,
    });
  },
};

export const AccountMenuLoading: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.loading,
        ...authHandlers.success,
        conversationListHandler,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Open account menu" }),
    );
    await expect(
      await within(document.body).findByText("Loading plan and Token Credits…"),
    ).toBeVisible();
  },
};

export const AccountMenuUnavailable: Story = {
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.unavailable,
        ...authHandlers.success,
        conversationListHandler,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Open account menu" }),
    );
    await expect(
      await within(document.body).findByRole("menuitem", {
        name: "Usage unavailable · Retry",
      }),
    ).toBeVisible();
  },
};

export const AccountMenuKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", {
      name: "Open account menu",
    });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const settingsItem = await within(document.body).findByRole("menuitem", {
      name: "Settings",
    });
    await expect(settingsItem).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(getRouter().replace).toHaveBeenCalledWith(
      "/?settings=general",
      { scroll: false },
    );
  },
};

export const AccountMenuPublicLinksKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", {
      name: "Open account menu",
    });
    trigger.focus();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowDown}{ArrowDown}");
    await expect(
      within(document.body).getByRole("menuitem", { name: "Documentation" }),
    ).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(
      within(document.body).getByRole("menuitem", { name: "Repository" }),
    ).toHaveFocus();
  },
};

export const MobileNavigation: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Open navigation" }),
    );
    const dialog = within(document.body).getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      within(dialog).getByRole("link", { name: actor.display_name }),
    ).toHaveAttribute("href", "/me");
    await expect(
      within(dialog).getByRole("button", { name: "Close navigation" }),
    ).toBeVisible();
    await expect(
      within(dialog).getByRole("link", { name: "New chat" }),
    ).toBeVisible();
    await expect(
      within(dialog).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    ).toBeVisible();
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "Search conversations and papers (⌘K)",
      }),
    );
    await expect(
      await within(document.body).findByRole("dialog", {
        name: "Search Scholens",
      }),
    ).toBeVisible();
  },
};

export const MobileConversationRename: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  parameters: {
    msw: {
      handlers: [
        ...billingHandlers.success,
        ...authHandlers.success,
        ...conversationMutationHandlers,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Open navigation" }),
    );
    const navigation = await body.findByRole("dialog", {
      name: "Open navigation",
    });
    await userEvent.click(
      await within(navigation).findByRole("button", {
        name: /Open actions for/,
      }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Rename" }),
    );
    const renameDialog = await body.findByRole("dialog", {
      name: "Rename conversation",
    });
    const input = within(renameDialog).getByRole("textbox", {
      name: "Conversation title",
    });
    await expect(input).toHaveFocus();
    await userEvent.clear(input);
    await userEvent.type(input, "Mobile research notes{Enter}");
    await waitFor(() => expect(renameDialog).not.toBeInTheDocument());
  },
};

export const MobileAccountEntry: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const primaryNavigation = canvas.getByRole("navigation", {
      name: "Primary navigation",
    });
    const meDestination = within(primaryNavigation).getByRole("link", {
      name: "Me",
    });
    await expect(meDestination).toHaveAttribute("href", "/me");
    await userEvent.click(
      canvas.getByRole("button", { name: "Open navigation" }),
    );
    const navigation = await body.findByRole("dialog");
    const identity = within(navigation).getByRole("link", { name: "Eric" });
    await expect(identity).toHaveAttribute("href", "/me");
    await expect(
      within(navigation).queryByRole("button", { name: "Settings" }),
    ).not.toBeInTheDocument();
    await expect(within(navigation).queryByText("24M / 100M")).toBeNull();
  },
};

export const AccountMenuDarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "打开账号菜单" }),
    );
    const menu = await within(document.body).findByRole("menu");
    await expect(await within(menu).findByText("研究者版")).toBeVisible();
    await expect(
      await within(menu).findByText("额度于 2026年8月17日 重置"),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "设置" }),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "账户" }),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "用量" }),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "文档" }),
    ).toBeVisible();
    await expect(
      within(menu).getByRole("menuitem", { name: "仓库" }),
    ).toBeVisible();
  },
};
