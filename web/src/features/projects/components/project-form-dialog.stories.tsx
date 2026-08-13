import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { authHandlers } from "../../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { ProjectFormDialog } from "./project-form-dialog";

const meta = {
  title: "Features/Projects/Project Form",
  component: ProjectFormDialog,
  args: { mode: "create", onOpenChange: fn(), onSubmit: fn(), open: true },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
  parameters: { msw: { handlers: authHandlers.success } },
} satisfies Meta<typeof ProjectFormDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Create: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Create a project" }),
    ).toBeVisible();
    await userEvent.click(body.getByRole("button", { name: "Create project" }));
    await expect(body.getByText("Enter a project name")).toBeVisible();
  },
};

export const EditLongContent: Story = {
  args: {
    initialValue: {
      description:
        "A cross-disciplinary project studying evidence quality, retrieval failures, and collaborative review protocols.",
      title:
        "Evidence quality across long-context collaborative research systems",
    },
    mode: "edit",
  },
};
