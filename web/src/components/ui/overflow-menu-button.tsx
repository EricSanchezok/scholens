"use client";

import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { MoreIcon } from "@/design-system/icons/semantic-icons";
import { cn } from "@/lib/utilities/cn";
import { IconButton, type ButtonProps } from "./button";

export type OverflowMenuButtonProps = Omit<
  ButtonProps,
  "children" | "size" | "variant"
> & {
  label: string;
  visibility?: "always" | "contextual";
};

export const OverflowMenuButton = React.forwardRef<
  HTMLButtonElement,
  OverflowMenuButtonProps
>(({ className, label, visibility = "always", ...props }, ref) => (
  <IconButton
    className={cn(
      "group/overflow size-11 transition-[background-color,color,opacity] duration-150 motion-reduce:transition-none sm:size-9 sm:min-h-9",
      visibility === "contextual" &&
        "group-focus-within/interactive-row:opacity-100! group-hover/interactive-row:opacity-100! group-data-[current]/interactive-row:opacity-100! focus-visible:opacity-100! data-[state=open]:opacity-100! [@media(hover:hover)]:opacity-0",
      className,
    )}
    label={label}
    ref={ref}
    variant="overflow"
    {...props}
  >
    <Icon
      className="group-hover/overflow:text-ui-icon-primary group-data-[state=open]/overflow:text-ui-icon-primary transition-colors duration-150 motion-reduce:transition-none"
      glyph={MoreIcon}
      size={20}
      tone="secondary"
    />
  </IconButton>
));
OverflowMenuButton.displayName = "OverflowMenuButton";
