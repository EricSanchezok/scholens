import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";
import { expect, userEvent, within } from "storybook/test";

import { ConfirmIcon } from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import { Button } from "./button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";

function RadioIndicatorMenu() {
  const [value, setValue] = React.useState("standard");

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary">Reasoning indicator examples</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup onValueChange={setValue} value={value}>
          <DropdownMenuRadioItem value="standard">
            Default leading dot
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem
            indicator={<Icon glyph={ConfirmIcon} size={16} />}
            indicatorPosition="end"
            value="deep"
          >
            Custom trailing check
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const meta = {
  title: "Actions/DropdownMenu",
  component: RadioIndicatorMenu,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
} satisfies Meta<typeof RadioIndicatorMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

export const RadioIndicators: Story = {
  globals: { viewport: { value: "smallMobile" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(canvasElement.ownerDocument.body);
    const trigger = canvas.getByRole("button", {
      name: "Reasoning indicator examples",
    });

    await userEvent.click(trigger);
    const leading = page.getByRole("menuitemradio", {
      name: "Default leading dot",
    });
    const trailing = page.getByRole("menuitemradio", {
      name: "Custom trailing check",
    });
    const leadingIndicator = leading.querySelector<HTMLElement>(
      '[data-slot="dropdown-menu-radio-indicator"]',
    );
    await expect(leading).toHaveAttribute("aria-checked", "true");
    await expect(leadingIndicator).not.toBeNull();
    await expect(leadingIndicator?.querySelector(".bg-primary")).not.toBeNull();
    await expect(leadingIndicator!.getBoundingClientRect().x).toBeLessThan(
      leading.getBoundingClientRect().x + leading.clientWidth / 2,
    );

    await userEvent.click(trailing);
    await userEvent.click(trigger);
    const selectedTrailing = page.getByRole("menuitemradio", {
      name: "Custom trailing check",
    });
    const trailingIndicator = selectedTrailing.querySelector<HTMLElement>(
      '[data-slot="dropdown-menu-radio-indicator"]',
    );
    await expect(selectedTrailing).toHaveAttribute("aria-checked", "true");
    await expect(trailingIndicator?.querySelector("svg")).not.toBeNull();
    await expect(trailingIndicator!.getBoundingClientRect().x).toBeGreaterThan(
      selectedTrailing.getBoundingClientRect().x +
        selectedTrailing.clientWidth / 2,
    );
  },
};
