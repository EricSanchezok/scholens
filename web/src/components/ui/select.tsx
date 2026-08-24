"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { cva, type VariantProps } from "class-variance-authority";
import { Check, NavArrowDown } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { focusSurfaceVariants } from "./focus";

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;
export const SelectValue = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Value>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Value>
>(({ className, ...props }, ref) => (
  <span
    className={cn(
      "min-w-0 flex-1 overflow-hidden text-left text-ellipsis whitespace-nowrap",
      className,
    )}
    data-slot="select-value"
  >
    <SelectPrimitive.Value ref={ref} {...props} />
  </span>
));
SelectValue.displayName = SelectPrimitive.Value.displayName;

export const selectTriggerVariants = cva(
  `motion-control group/select border-line bg-surface hover:bg-subtle data-[state=open]:bg-subtle active:bg-pressed disabled:text-disabled flex w-full items-center justify-between gap-2 rounded-[var(--radius-lg)] border px-3 text-sm disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-subtle aria-invalid:border-[var(--color-danger-border)] ${focusSurfaceVariants({ intent: "neutral" })}`,
  {
    variants: {
      variant: {
        field: "h-11",
        compact: "h-11 sm:h-9",
      },
    },
    defaultVariants: { variant: "field" },
  },
);

export type SelectTriggerProps = React.ComponentPropsWithoutRef<
  typeof SelectPrimitive.Trigger
> &
  VariantProps<typeof selectTriggerVariants>;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  SelectTriggerProps
>(({ children, className, variant, ...props }, ref) => (
  <SelectPrimitive.Trigger
    className={cn(selectTriggerVariants({ variant }), className)}
    ref={ref}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon
      className="motion-icon shrink-0 group-data-[state=open]/select:rotate-180"
      data-slot="select-indicator"
    >
      <Icon glyph={NavArrowDown} size={16} tone="secondary" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;
export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(
  (
    { children, className, position = "popper", sideOffset = 6, ...props },
    ref,
  ) => (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        className={cn(
          "motion-popup bg-elevated shadow-raised z-[90] max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-lg)] p-1.5",
          className,
        )}
        position={position}
        ref={ref}
        sideOffset={sideOffset}
        {...props}
      >
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  ),
);
SelectContent.displayName = SelectPrimitive.Content.displayName;
export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ children, className, ...props }, ref) => (
  <SelectPrimitive.Item
    className={cn(
      "data-[highlighted]:bg-hover data-[state=checked]:bg-subtle data-[disabled]:text-disabled relative flex min-h-11 cursor-default items-center rounded-[var(--radius-md)] py-2 pr-9 pl-3 text-sm outline-none select-none data-[disabled]:pointer-events-none sm:min-h-9",
      className,
    )}
    ref={ref}
    {...props}
  >
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    <span className="absolute right-3">
      <SelectPrimitive.ItemIndicator>
        <Icon glyph={Check} size={16} />
      </SelectPrimitive.ItemIndicator>
    </span>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;
export const SelectLabel = (
  props: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>,
) => (
  <SelectPrimitive.Label
    className="text-muted px-3 py-2 text-xs font-medium"
    {...props}
  />
);
export const SelectSeparator = (
  props: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>,
) => <SelectPrimitive.Separator className="bg-line my-1 h-px" {...props} />;
