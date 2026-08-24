"use client";

import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { Check } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { focusSurfaceVariants } from "./focus";

export const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    className={cn(
      "motion-control border-control bg-surface text-primary-foreground hover:bg-hover data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:hover:bg-primary-hover grid size-5 place-items-center rounded-[var(--radius-xs)] border disabled:opacity-[var(--opacity-disabled)]",
      focusSurfaceVariants({ intent: "selection" }),
      className,
    )}
    data-selection-control="checkbox"
    ref={ref}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className="settled-content-enter"
      data-selection-indicator=""
    >
      <Icon glyph={Check} size={16} tone="inverse" />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
));
Checkbox.displayName = CheckboxPrimitive.Root.displayName;

export const RadioGroup = RadioGroupPrimitive.Root;
export const RadioItem = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitive.Item
    className={cn(
      "motion-control border-control bg-surface hover:bg-hover data-[state=checked]:border-primary data-[state=checked]:hover:bg-subtle grid size-5 place-items-center rounded-full border disabled:opacity-[var(--opacity-disabled)]",
      focusSurfaceVariants({ intent: "selection" }),
      className,
    )}
    data-selection-control="radio"
    ref={ref}
    {...props}
  >
    <RadioGroupPrimitive.Indicator
      className="bg-primary size-2.5 rounded-full"
      data-selection-indicator=""
    />
  </RadioGroupPrimitive.Item>
));
RadioItem.displayName = RadioGroupPrimitive.Item.displayName;

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    className={cn(
      "motion-control bg-secondary-action hover:bg-hover data-[state=checked]:bg-primary data-[state=checked]:hover:bg-primary-hover h-6 w-11 rounded-full p-0.5 disabled:opacity-[var(--opacity-disabled)]",
      focusSurfaceVariants({ intent: "selection" }),
      className,
    )}
    data-selection-control="switch"
    ref={ref}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className="motion-icon bg-surface block size-5 rounded-full shadow-sm data-[state=checked]:translate-x-5"
      data-selection-thumb=""
    />
  </SwitchPrimitive.Root>
));
Switch.displayName = SwitchPrimitive.Root.displayName;
