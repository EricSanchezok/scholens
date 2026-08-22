import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import {
  SearchField,
  Select,
  SelectContent,
  SelectItem,
} from "@/components/ui";
import { FilterIcon, TagIcon } from "@/design-system/icons/semantic-icons";
import {
  CollectionToolbar,
  CollectionToolbarButton,
  CollectionToolbarSelectTrigger,
} from "./collection-toolbar";

function CollectionToolbarPreview() {
  return (
    <div className="min-w-0">
      <CollectionToolbar
        controls={
          <>
            <CollectionToolbarButton glyph={FilterIcon} label="Status" />
            <CollectionToolbarButton count={2} glyph={TagIcon} label="Tags" />
            <Select defaultValue="recent">
              <CollectionToolbarSelectTrigger label="Sort papers" />
              <SelectContent>
                <SelectItem value="recent">Recently added</SelectItem>
                <SelectItem value="title">Title</SelectItem>
              </SelectContent>
            </Select>
          </>
        }
        meta="27 papers"
        search={
          <SearchField aria-label="Search papers" placeholder="Search papers" />
        }
      />
    </div>
  );
}

const meta = {
  title: "Features/Paper Collection/Collection Toolbar",
  component: CollectionToolbarPreview,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="mx-auto w-full max-w-5xl p-4">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof CollectionToolbarPreview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Mobile: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toolbar = canvasElement.querySelector<HTMLElement>(
      "[data-collection-toolbar]",
    );
    const search = canvas.getByRole("searchbox", { name: "Search papers" });
    const status = canvas.getByRole("button", { name: "Status" });
    const tags = canvas.getByRole("button", { name: "Tags" });
    const sort = canvas.getByRole("combobox", { name: "Sort papers" });
    await expect(toolbar).not.toBeNull();
    await expect(tags).toHaveAccessibleDescription("2");
    await expect(toolbar!.closest('[data-slot="frame"]')).toBeNull();
    const boxes = [search, status, tags, sort].map((element) =>
      element.getBoundingClientRect(),
    );
    await expect(
      Math.max(...boxes.map((box) => box.top)) -
        Math.min(...boxes.map((box) => box.top)),
    ).toBeLessThanOrEqual(1);
    await expect(toolbar!.scrollWidth).toBeLessThanOrEqual(
      toolbar!.clientWidth,
    );
    await expect(canvas.getByText("27 papers")).not.toBeVisible();
  },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};
