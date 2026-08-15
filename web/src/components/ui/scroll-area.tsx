"use client";

import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";
import * as VisuallyHiddenPrimitive from "@radix-ui/react-visually-hidden";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

export const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ children, className, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    className={cn("relative overflow-hidden", className)}
    ref={ref}
    {...props}
  >
    <ScrollAreaPrimitive.Viewport
      className="size-full rounded-[inherit]"
      data-scrollbar-gutter="stable"
      tabIndex={0}
    >
      {children}
    </ScrollAreaPrimitive.Viewport>
    {(["vertical", "horizontal"] as const).map((orientation) => (
      <ScrollAreaPrimitive.Scrollbar
        className={cn(
          "flex touch-none p-0.5 select-none",
          orientation === "vertical"
            ? "w-[var(--scrollbar-box)]"
            : "h-[var(--scrollbar-box)] flex-col",
        )}
        key={orientation}
        orientation={orientation}
      >
        <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-[var(--color-scrollbar-thumb)] hover:bg-[var(--color-scrollbar-thumb-hover)]" />
      </ScrollAreaPrimitive.Scrollbar>
    ))}
    <ScrollAreaPrimitive.Corner className="bg-transparent" />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

export const VisuallyHidden = VisuallyHiddenPrimitive.Root;
