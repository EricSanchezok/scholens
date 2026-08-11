import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";
import * as React from "react";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import type { components } from "@/lib/api/generated/schema";
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
}: {
  activeDestination?: "ask" | "library" | "projects";
  storyActor?: typeof actor;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  return (
    <WorkspaceShell
      activeDestination={activeDestination}
      actor={storyActor}
      collapsed={collapsed}
      conversations={conversations}
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
    msw: { handlers: authHandlers.success },
    nextjs: { appDirectory: true },
  },
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

    await expect(name).toHaveStyle({ fontSize: "13px" });
    await expect(conversation).toHaveStyle({ fontSize: "13px" });
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
