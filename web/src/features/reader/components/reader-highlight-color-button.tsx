import * as React from "react";

import { focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import {
  readerHighlightColorValue,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";

type ReaderHighlightColorButtonProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "color"
> & {
  color: ReaderHighlightColor;
  label: string;
  selected?: boolean;
};

export function ReaderHighlightColorButton({
  className,
  color,
  label,
  selected,
  ...props
}: ReaderHighlightColorButtonProps) {
  return (
    <button
      {...props}
      aria-label={label}
      aria-pressed={selected === undefined ? undefined : selected}
      className={cn(
        "motion-control relative isolate grid size-9 shrink-0 place-items-center rounded-full after:absolute after:-inset-1 after:content-['']",
        focusSurfaceVariants({ intent: "neutral" }),
        className,
      )}
      type="button"
    >
      <span
        aria-hidden="true"
        className={cn(
          "border-control pointer-events-none relative size-6 rounded-full border",
          selected &&
            "ring-2 ring-[var(--color-action-primary)] ring-offset-2 ring-offset-[var(--color-bg-surface)]",
        )}
        data-reader-highlight-swatch=""
        data-selected={selected || undefined}
        style={{ backgroundColor: readerHighlightColorValue(color) }}
      />
    </button>
  );
}
