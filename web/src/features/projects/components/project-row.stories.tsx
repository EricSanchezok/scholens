import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { authHandlers } from "../../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { projectFixtures } from "../api/fixtures";
import { ProjectRow } from "./project-row";

const meta = {
  title: "Features/Projects/Project Row",
  component: ProjectRow,
  args: {
    onDelete: fn(),
    onEdit: fn(),
    onLeave: fn(),
    project: projectFixtures[0]!,
  },
  decorators: [
    (Story) => (
      <Providers>
        <div className="max-w-4xl p-4">
          <Story />
        </div>
      </Providers>
    ),
  ],
  parameters: {
    msw: { handlers: authHandlers.success },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof ProjectRow>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Owner: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Truthward" })).toBeVisible();
    await expect(canvas.getByText("18")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Open project actions" }),
    );
    await expect(
      await within(document.body).findByText("Rename"),
    ).toBeVisible();
    await expect(within(document.body).getByText("Delete")).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const Collaborator: Story = {
  args: { project: projectFixtures[1]! },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Open project actions",
      }),
    );
    await expect(
      await within(document.body).findByText("Leave project"),
    ).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="w-72 p-2">
        <Story />
      </div>
    ),
  ],
};
