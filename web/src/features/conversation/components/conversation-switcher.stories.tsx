import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import {
  ConversationSwitcher,
  type ConversationSummary,
  type ConversationSwitcherLabels,
} from "./conversation-switcher";

const labels: ConversationSwitcherLabels = {
  empty: "No matching conversations",
  loading: "Loading conversations",
  new: "New conversation",
  newDraft: "New conversation",
  pin: "Pin conversation",
  pinned: "Pinned",
  recent: "Recent",
  search: "Search conversations",
  switcher: "Conversation history",
  unpin: "Unpin conversation",
};

const capabilities = {
  archive: true,
  delete: true,
  detach: false,
  move: false,
  pin: true,
  rename: true,
  send: true,
  share: false,
};

const conversations: ConversationSummary[] = [
  {
    archived_at: null,
    capabilities,
    id: "40000000-0000-4000-8000-000000000001",
    pinned_at: "2026-08-12T10:05:00Z",
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: "50000000-0000-4000-8000-000000000001",
    scope_label: "Truthward",
    scope_type: "project",
    title: "Compare the evaluation methods",
    updated_at: "2026-08-12T10:05:00Z",
  },
  {
    archived_at: null,
    capabilities,
    id: "40000000-0000-4000-8000-000000000002",
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: "50000000-0000-4000-8000-000000000001",
    scope_label: "Truthward",
    scope_type: "project",
    title:
      "Summarize the central contribution and compare it with our current evidence",
    updated_at: "2026-08-12T09:05:00Z",
  },
];

const meta = {
  title: "Features/Conversation/Switcher",
  component: ConversationSwitcher,
  args: {
    activeId: conversations[0]!.id,
    conversations,
    labels,
    loading: false,
    onChange: fn(),
    onNew: fn(),
    onPin: fn(async () => undefined),
    onPinError: fn(),
  },
  decorators: [
    (Story) => (
      <div className="bg-canvas h-72 w-full max-w-md">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ConversationSwitcher>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Closed: Story = {};

export const HistoryOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", {
      name: "Compare the evaluation methods",
    });
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(
      within(document.body).getByPlaceholderText("Search conversations"),
    ).toBeVisible();
    await expect(within(document.body).getByText("Pinned")).toBeVisible();
    await expect(within(document.body).getByText("Recent")).toBeVisible();
  },
};

export const SearchEmpty: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Compare the evaluation methods" }),
    );
    const body = within(document.body);
    await userEvent.type(
      body.getByPlaceholderText("Search conversations"),
      "missing",
    );
    await expect(body.getByText("No matching conversations")).toBeVisible();
  },
};

export const Loading: Story = {
  args: { conversations: [], loading: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getAllByRole("button", { name: "New conversation" })[0]!,
    );
    await expect(
      within(document.body).getByText("Loading conversations"),
    ).toBeVisible();
  },
};

export const Narrow: Story = {
  globals: { viewport: { value: "smallMobile" } },
  decorators: [
    (Story) => (
      <div className="bg-canvas h-72 w-[20rem] max-w-full">
        <Story />
      </div>
    ),
  ],
};
