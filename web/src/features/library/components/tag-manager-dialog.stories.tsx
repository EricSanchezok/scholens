import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";
import { expect, userEvent, within } from "storybook/test";

import { authHandlers } from "../../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { Button } from "@/components/ui";
import { libraryTags } from "../api/fixtures";
import { TagManagerDialog, type LibraryTag } from "./tag-manager-dialog";

function TagManagerHarness({
  assigning = true,
  empty = false,
}: {
  assigning?: boolean;
  empty?: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const [tags, setTags] = React.useState<LibraryTag[]>(
    empty ? [] : libraryTags,
  );
  const [saved, setSaved] = React.useState<string[]>(
    assigning ? [libraryTags[0]!.id] : [],
  );

  return (
    <div className="bg-canvas min-h-screen p-6">
      <Button onClick={() => setOpen(true)} variant="secondary">
        Open tag manager
      </Button>
      <output className="text-secondary ml-4 text-sm">{saved.join(",")}</output>
      <TagManagerDialog
        documentIds={assigning ? ["paper-1", "paper-2"] : []}
        initialTagIds={saved}
        onCreate={async (name) => {
          const created = {
            color: null,
            id: `created-${name.toLocaleLowerCase().replaceAll(" ", "-")}`,
            name,
          };
          setTags((current) => [...current, created]);
          return created;
        }}
        onDelete={async (tagId) => {
          setTags((current) => current.filter((tag) => tag.id !== tagId));
        }}
        onOpenChange={setOpen}
        onRename={async (tagId, name) => {
          const renamed = tags.find((tag) => tag.id === tagId)!;
          const next = { ...renamed, name };
          setTags((current) =>
            current.map((tag) => (tag.id === tagId ? next : tag)),
          );
          return next;
        }}
        onSave={async (_documentIds, tagIds) => setSaved(tagIds)}
        open={open}
        tags={tags}
      />
    </div>
  );
}

const meta = {
  title: "Features/Library/Tag manager dialog",
  component: TagManagerHarness,
  args: { assigning: true, empty: false },
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
  },
} satisfies Meta<typeof TagManagerHarness>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AssignAndCreate: Story = {
  play: async () => {
    const page = within(document.body);
    await expect(
      await page.findByRole("heading", { name: "Edit tags" }),
    ).toBeVisible();
    await expect(
      page.getByRole("checkbox", { name: "Transformers" }),
    ).toBeChecked();
    await userEvent.type(page.getByLabelText("New tag name"), "Reading queue");
    await userEvent.click(page.getByRole("button", { name: "Create" }));
    await expect(page.getByText("Reading queue")).toBeVisible();
    await userEvent.click(page.getByRole("button", { name: "Apply tags" }));
    await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const EmptyManagement: Story = {
  args: { assigning: false, empty: true },
  play: async () => {
    const page = within(document.body);
    await expect(
      await page.findByRole("heading", { name: "Manage tags" }),
    ).toBeVisible();
    await expect(page.getByText("No tags yet")).toBeVisible();
    await userEvent.type(page.getByLabelText("New tag name"), "Methods");
    await userEvent.click(page.getByRole("button", { name: "Create" }));
    await expect(page.getByText("Methods")).toBeVisible();
  },
};

export const RenameLifecycle: Story = {
  args: { assigning: false, empty: false },
  play: async () => {
    const page = within(document.body);
    await page.findByRole("heading", { name: "Manage tags" });
    await userEvent.click(
      page.getByRole("button", { name: "Actions for Transformers" }),
    );
    await userEvent.click(page.getByRole("menuitem", { name: "Rename" }));
    const input = page.getByLabelText("Rename Transformers");
    await userEvent.clear(input);
    await userEvent.type(input, "Foundation models");
    await userEvent.click(page.getByRole("button", { name: "Save" }));
    await expect(page.getByText("Foundation models")).toBeVisible();
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog");
    await expect(dialog.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      window.innerHeight,
    );
    await expect(
      within(dialog).getByRole("heading", { name: "Edit tags" }),
    ).toBeVisible();
  },
};

export const Mobile320ChineseEmpty: Story = {
  args: { assigning: false, empty: true },
  globals: {
    locale: "zh-CN",
    viewport: { value: "smallMobile", isRotated: false },
  },
  play: async () => {
    const page = within(document.body);
    await expect(
      await page.findByRole("heading", { name: "管理标签" }),
    ).toBeVisible();
    await expect(page.getByText("还没有标签")).toBeVisible();
  },
};
