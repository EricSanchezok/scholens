import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type SelectTriggerProps,
} from "./select";

function LanguageSelect({
  disabled = false,
  variant = "field",
}: {
  disabled?: boolean;
  variant?: SelectTriggerProps["variant"];
}) {
  return (
    <Select defaultValue="en" disabled={disabled}>
      <SelectTrigger aria-label="Language" variant={variant}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="en">English</SelectItem>
        <SelectItem value="zh-CN">简体中文</SelectItem>
      </SelectContent>
    </Select>
  );
}

function SelectInDialog() {
  return (
    <Dialog defaultOpen>
      <DialogContent closeLabel="Close settings">
        <DialogHeader>
          <DialogTitle>Appearance & language</DialogTitle>
          <DialogDescription>
            Choose the language used by this interface.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <LanguageSelect />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function LongValueSelect() {
  return (
    <div className="w-40">
      <Select defaultValue="long">
        <SelectTrigger aria-label="Reader context" variant="compact">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="long">
            A deliberately long research project title that must stay on one
            line
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

const meta = {
  title: "Forms/Select",
  component: LanguageSelect,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,20rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof LanguageSelect>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-3">
      <LanguageSelect />
      <LanguageSelect disabled />
    </div>
  ),
};
export const VisualVariants: Story = {
  render: () => (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <span className="text-caption text-secondary">Default density</span>
        <LanguageSelect variant="field" />
      </div>
      <div className="grid gap-2">
        <span className="text-caption text-secondary">Compact density</span>
        <LanguageSelect variant="compact" />
      </div>
    </div>
  ),
};
export const KeyboardInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("combobox", { name: "Language" });
    await userEvent.click(trigger);
    const listbox = await within(document.body).findByRole("listbox");
    const popup = listbox.closest<HTMLElement>(".motion-popup");
    await expect(popup).not.toBeNull();
    const style = getComputedStyle(popup!);
    const radixOrigin = style
      .getPropertyValue("--radix-select-content-transform-origin")
      .trim();
    await expect(radixOrigin).not.toBe("");
    const [originX = Number.NaN, originY = Number.NaN] = style.transformOrigin
      .split(" ")
      .map((value) => Number.parseFloat(value));
    await expect(originX).toBeCloseTo(0, 1);
    await expect(originY).toBeCloseTo(0, 1);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await expect(trigger).toHaveTextContent("简体中文");
  },
};
export const DialogLayering: Story = {
  render: () => <SelectInDialog />,
  play: async () => {
    const body = within(document.body);
    const dialog = await body.findByRole("dialog");
    const trigger = await body.findByRole("combobox", { name: "Language" });
    await expect(window.getComputedStyle(dialog).outlineStyle).toBe("none");
    await userEvent.click(trigger);
    await userEvent.click(
      await body.findByRole("option", { name: "简体中文" }),
    );
    await expect(trigger).toHaveTextContent("简体中文");
  },
};
export const LongValue: StoryObj<typeof LongValueSelect> = {
  render: () => <LongValueSelect />,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("combobox", {
      name: "Reader context",
    });
    const value = trigger.querySelector("[data-slot]") ?? trigger.firstChild;
    await expect(trigger.scrollWidth).toBeLessThanOrEqual(trigger.clientWidth);
    await expect(value).not.toBeNull();
    await expect(window.getComputedStyle(value as Element).whiteSpace).toBe(
      "nowrap",
    );
  },
};
