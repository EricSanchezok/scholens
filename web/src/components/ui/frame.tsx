import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

const frameVariants = cva(
  "relative flex min-w-0 flex-col rounded-[var(--frame-radius)] [--frame-panel-radius:calc(var(--frame-radius)-var(--frame-inset))] [--frame-radius:var(--radius-xl)]",
  {
    variants: {
      variant: {
        default: "border-line bg-subtle border",
        ghost: "bg-subtle",
        transparent: "bg-transparent",
      },
      spacing: {
        compact: "gap-1 p-1 [--frame-inset:0.25rem]",
        default: "gap-1.5 p-1.5 [--frame-inset:0.375rem]",
        roomy: "gap-2 p-2 [--frame-inset:0.5rem]",
      },
    },
    defaultVariants: {
      spacing: "default",
      variant: "default",
    },
  },
);

export type FrameProps = React.HTMLAttributes<HTMLDivElement> &
  VariantProps<typeof frameVariants> & {
    asChild?: boolean;
  };

export const Frame = React.forwardRef<HTMLDivElement, FrameProps>(
  ({ asChild, className, spacing, variant, ...props }, ref) => {
    const Comp = asChild ? Slot : "div";
    return (
      <Comp
        className={cn(frameVariants({ spacing, variant }), className)}
        data-slot="frame"
        ref={ref}
        {...props}
      />
    );
  },
);
Frame.displayName = "Frame";

const framePanelVariants = cva(
  "relative min-w-0 overflow-hidden rounded-[var(--frame-panel-radius)]",
  {
    variants: {
      variant: {
        raised: "border-line bg-surface shadow-raised border",
        flat: "border-line bg-surface border",
        ghost: "bg-surface",
      },
      spacing: {
        none: "p-0",
        compact: "p-2.5",
        default: "p-3",
        roomy: "p-4",
      },
    },
    defaultVariants: {
      spacing: "default",
      variant: "raised",
    },
  },
);

export type FramePanelProps = React.HTMLAttributes<HTMLDivElement> &
  VariantProps<typeof framePanelVariants> & {
    asChild?: boolean;
  };

export const FramePanel = React.forwardRef<HTMLDivElement, FramePanelProps>(
  ({ asChild, className, spacing, variant, ...props }, ref) => {
    const Comp = asChild ? Slot : "div";
    return (
      <Comp
        className={cn(framePanelVariants({ spacing, variant }), className)}
        data-slot="frame-panel"
        ref={ref}
        {...props}
      />
    );
  },
);
FramePanel.displayName = "FramePanel";

export { framePanelVariants, frameVariants };
