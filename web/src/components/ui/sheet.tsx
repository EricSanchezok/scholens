"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cva, type VariantProps } from "class-variance-authority";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { IconButton } from "./button";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;

const sheetContentVariants = cva(
  "border-line bg-elevated shadow-panel fixed z-50 p-6",
  {
    variants: {
      side: {
        bottom: "motion-bottom-sheet inset-x-0 bottom-0 w-full border-t",
        left: "motion-side-sheet-left inset-y-0 left-0 w-[min(90vw,30rem)] border-r",
        right:
          "motion-side-sheet inset-y-0 right-0 w-[min(90vw,30rem)] border-l",
      },
    },
    defaultVariants: { side: "right" },
  },
);

export const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    closeLabel: string;
    closeGlyph?: IconGlyph;
    showCloseButton?: boolean;
  } & VariantProps<typeof sheetContentVariants>
>(
  (
    {
      children,
      className,
      closeGlyph = Xmark,
      closeLabel,
      showCloseButton = true,
      side = "right",
      ...props
    },
    ref,
  ) => (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className="motion-overlay fixed inset-0 z-40 bg-[var(--color-overlay-backdrop)]"
        data-slot="sheet-overlay"
      />
      <DialogPrimitive.Content
        className={cn(sheetContentVariants({ side }), className)}
        data-side={side}
        data-slot="sheet-content"
        ref={ref}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close asChild>
            <IconButton
              className="absolute top-3 right-3"
              label={closeLabel}
              variant="ghost"
            >
              <Icon glyph={closeGlyph} size={24} />
            </IconButton>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  ),
);
SheetContent.displayName = DialogPrimitive.Content.displayName;
