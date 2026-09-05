import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { focusSurfaceVariants } from "@/components/ui";
import { ContextualLink } from "./contextual-link";

const meta = {
  title: "Features/Workspace Navigation/Contextual Link",
  component: ContextualLink,
  args: {
    children: "Open paper",
    className: focusSurfaceVariants({ intent: "inline" }),
    focusKey: "document-1",
    href: "/reader/document-1?project=project-1",
    originKind: "library",
  },
  decorators: [
    (Story) => (
      <div className="max-w-72 p-4 text-sm">
        <Story />
      </div>
    ),
  ],
  parameters: { nextjs: { appDirectory: true } },
} satisfies Meta<typeof ContextualLink>;

export default meta;
type Story = StoryObj<typeof meta>;

export const CanonicalDestination: Story = {
  play: async ({ canvasElement }) => {
    const link = within(canvasElement).getByRole("link", {
      name: "Open paper",
    });
    await expect(link).toHaveAttribute(
      "href",
      "/reader/document-1?project=project-1",
    );
    await userEvent.tab();
    await expect(link).toHaveFocus();
  },
};
