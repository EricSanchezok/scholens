"use client";

import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";
import * as VisuallyHiddenPrimitive from "@radix-ui/react-visually-hidden";
import * as React from "react";

import { scrollbarTrackRemovalDelayMs } from "@/design-system/scrollbars/scrollbar-activity";
import { cn } from "@/lib/utilities/cn";
import { focusSurfaceVariants } from "./focus";

export const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ children, className, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    className={cn("relative overflow-hidden", className)}
    data-scrollbar-root=""
    ref={ref}
    scrollHideDelay={scrollbarTrackRemovalDelayMs}
    type="scroll"
    {...props}
  >
    <ScrollAreaPrimitive.Viewport
      className={cn(
        "size-full rounded-[inherit]",
        focusSurfaceVariants({ intent: "scroll" }),
      )}
      data-scrollbar-gutter="stable"
      tabIndex={0}
    >
      {children}
    </ScrollAreaPrimitive.Viewport>
    {(["vertical", "horizontal"] as const).map((orientation) => (
      <ScrollAreaPrimitive.Scrollbar
        className={cn(
          "flex touch-none p-px select-none",
          orientation === "vertical"
            ? "w-[var(--scrollbar-box)]"
            : "h-[var(--scrollbar-box)] flex-col",
        )}
        data-scrollbar-track=""
        key={orientation}
        orientation={orientation}
      >
        <ScrollAreaPrimitive.Thumb
          className="relative flex-1 rounded-full"
          data-scrollbar-thumb=""
        />
      </ScrollAreaPrimitive.Scrollbar>
    ))}
    <ScrollAreaPrimitive.Corner className="bg-transparent" />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

export const VisuallyHidden = VisuallyHiddenPrimitive.Root;
