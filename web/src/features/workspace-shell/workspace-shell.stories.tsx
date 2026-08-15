import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { getRouter } from "@storybook/nextjs-vite/navigation.mock";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { http, HttpResponse } from "msw";
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

const longIdentityActor = {
  ...actor,
  display_name: "EricSanchez",
  email: "niexiaohangeric@163.com",
};

function ShellStory({
  activeDestination = "library",
  storyActor = actor,
  storyConversations = conversations,
}: {
  activeDestination?: "ask" | "library" | "projects";
  storyActor?: typeof actor;
  storyConversations?: Conversation[];
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  return (
    <WorkspaceShell
      activeDestination={activeDestination}
      actor={storyActor}
      collapsed={collapsed}
      conversations={storyConversations}
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
      handlers: [...billingHandlers.success, ...authHandlers.success],
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
    await expect(canvas.getByRole("link", { name: "Library" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  },
};

export const DesktopLongContent: Story = {
  args: { storyActor: longIdentityActor },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const account = canvas.getByRole("button", { name: "Open account menu" });
    const name = within(account).getByText(longIdentityActor.display_name);
    const email = within(account).getByText(longIdentityActor.email);
    const conversation = canvas.getByText(conversations[0]!.title);
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

export const DesktopCollapsed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Collapse sidebar" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Expand sidebar" }),
    ).toBeVisible();
  },
};

const conversationMutationHandlers = [
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
    const row = canvasElement.querySelector(
      `[data-conversation-row="${conversations[0]!.id}"]`,
    );
    await expect(row).not.toBeNull();
    await userEvent.hover(row as Element);
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

    await userEvent.hover(row as Element);
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
    const row = canvasElement.querySelector(
      `[data-conversation-row="${conversations[0]!.id}"]`,
    );
    await userEvent.hover(row as Element);
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
    const row = canvasElement.querySelector("[data-conversation-row]");
    await userEvent.hover(row as Element);
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
    const row = canvasElement.querySelector("[data-conversation-row]");
    await userEvent.hover(row as Element);
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
    await expect(row as Element).toBeInTheDocument();
    await expect(
      await body.findByText("Conversation could not be updated. Try again."),
    ).toBeVisible();
  },
};

export const ConversationPermissions: Story = {
  args: {
    storyConversations: [
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
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const row = canvasElement.querySelector("[data-conversation-row]");
    await userEvent.hover(row as Element);
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
    msw: { handlers: [...billingHandlers.loading, ...authHandlers.success] },
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
      handlers: [...billingHandlers.unavailable, ...authHandlers.success],
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
      within(dialog).getByRole("searchbox", {
        name: "Search conversations",
      }),
    ).toBeVisible();
    await expect(
      within(dialog).getByRole("link", { name: "New chat" }),
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
      within(navigation).getByRole("button", { name: /Open actions for/ }),
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

export const MobileAccountMenu: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Open navigation" }),
    );
    const navigation = await body.findByRole("dialog");
    await userEvent.click(
      within(navigation).getByRole("button", { name: "Settings" }),
    );
    const menu = await body.findByRole("menu");
    await expect(await within(menu).findByText("24M / 100M")).toBeVisible();
    await userEvent.click(
      within(menu).getByRole("menuitem", { name: "Usage" }),
    );
    await expect(getRouter().replace).toHaveBeenCalledWith("/?settings=usage", {
      scroll: false,
    });
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
  },
};
