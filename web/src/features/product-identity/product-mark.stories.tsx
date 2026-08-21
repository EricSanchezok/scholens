import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { ProductLockup, ProductMark } from "./product-mark";

function ProductIdentityPreview() {
  return (
    <div className="bg-canvas text-foreground grid min-h-80 content-center justify-items-start gap-8 p-10">
      <ProductLockup className="text-lg font-semibold" size="standard" />
      <div className="flex items-end gap-6">
        <ProductMark size="compact" />
        <ProductMark size="standard" />
        <ProductMark size="display" />
      </div>
    </div>
  );
}

const meta = {
  title: "Features/Product Identity",
  component: ProductIdentityPreview,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ProductIdentityPreview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Scholens")).toBeVisible();
    await expect(
      canvasElement.querySelectorAll('[data-product-mark="portrait"]'),
    ).toHaveLength(4);
  },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};
