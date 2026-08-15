import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ConversationUserMessage } from "./conversation-user-message";

const meta = {
  title: "Features/Conversation/User Message",
  component: ConversationUserMessage,
  args: {
    branch: { count: 1, index: 1 },
    canEdit: true,
    message: "How does this result compare with the paper’s baseline?",
    onEdit: fn(async () => undefined),
    onSelectBranch: fn(),
  },
  decorators: [
    (Story) => (
      <main className="mx-auto w-full max-w-[var(--layout-conversation-lane)] p-5">
        <Story />
      </main>
    ),
  ],
} satisfies Meta<typeof ConversationUserMessage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Editing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit message" }));
    await expect(
      canvas.getByRole("form", { name: "Edit message" }),
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

export const RejectedEdit: Story = {
  args: {
    onEdit: fn(async () => {
      throw new Error("Preflight rejected");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit message" }));
    const editor = canvas.getByRole("textbox", { name: "Message text" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "Keep this draft after a capacity rejection");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(editor).toHaveValue(
      "Keep this draft after a capacity rejection",
    );
    await expect(canvas.getByRole("alert")).toHaveTextContent(
      /Your edit is still here/,
    );
    await expect(editor).toHaveFocus();
  },
};

export const Branched: Story = {
  args: {
    branch: {
      count: 3,
      index: 2,
      previous_turn_id: "previous-turn",
      next_turn_id: "next-turn",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Message 2 of 3")).toBeVisible();
  },
};

export const NarrowLongContent: Story = {
  args: {
    message:
      "Compare the paper’s methodology with https://example.com/a/very/long/unbroken/research/path/that/must/not/widen/the/conversation",
  },
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};

export const SimplifiedChineseDark: Story = {
  args: {
    branch: {
      count: 2,
      index: 2,
      previous_turn_id: "previous-turn",
    },
    message: "它与论文中的基线方法相比有什么优势？",
  },
  globals: { appearance: "dark", locale: "zh-CN" },
};
