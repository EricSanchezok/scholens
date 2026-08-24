"use client";

import * as React from "react";

import {
  Button,
  type ButtonProps,
  SelectTrigger,
  type SelectTriggerProps,
  SelectValue,
} from "@/components/ui";
import { Badge } from "@/components/ui/display";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import { SortIcon } from "@/design-system/icons/semantic-icons";
import { cn } from "@/lib/utilities/cn";

export function CollectionToolbar({
  className,
  controls,
  meta,
  search,
}: {
  className?: string;
  controls: React.ReactNode;
  meta?: React.ReactNode;
  search: React.ReactNode;
}) {
  return (
    <div
      className={cn("flex min-w-0 flex-nowrap items-center gap-2", className)}
      data-collection-toolbar=""
    >
      <div
        className="min-w-24 flex-1 overflow-hidden"
        data-collection-toolbar-search=""
      >
        {search}
      </div>
      <div
        className="flex shrink-0 flex-nowrap items-center gap-2"
        data-collection-toolbar-controls=""
      >
        {controls}
      </div>
      {meta ? (
        <div
          className="text-secondary ml-auto hidden shrink-0 text-sm xl:block"
          data-collection-toolbar-meta=""
        >
          {meta}
        </div>
      ) : null}
    </div>
  );
}

export const CollectionToolbarButton = React.forwardRef<
  HTMLButtonElement,
  Omit<ButtonProps, "children"> & {
    count?: number;
    glyph: IconGlyph;
    label: string;
  }
>(
  (
    { className, count = 0, glyph, label, variant = "secondary", ...props },
    ref,
  ) => {
    const countDescriptionId = React.useId();
    return (
      <Button
        aria-describedby={count > 0 ? countDescriptionId : undefined}
        aria-label={label}
        className={cn(
          "relative size-11 gap-0 rounded-full px-0 sm:h-11 sm:w-auto sm:gap-2 sm:px-4",
          className,
        )}
        ref={ref}
        title={label}
        variant={variant}
        {...props}
      >
        <Icon className="sm:hidden" glyph={glyph} size={20} tone="secondary" />
        <span className="hidden sm:inline">{label}</span>
        {count > 0 ? (
          <Badge
            className="absolute -top-1 -right-1 min-w-5 justify-center px-1 sm:static sm:min-w-0 sm:px-2"
            id={countDescriptionId}
            tone="neutral"
          >
            {count}
          </Badge>
        ) : null}
      </Button>
    );
  },
);
CollectionToolbarButton.displayName = "CollectionToolbarButton";

export const CollectionToolbarSelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectTrigger>,
  Omit<SelectTriggerProps, "children"> & {
    glyph?: IconGlyph;
    label: string;
  }
>(({ className, glyph = SortIcon, label, ...props }, ref) => (
  <SelectTrigger
    aria-label={label}
    className={cn(
      "size-11 shrink-0 justify-center gap-0 rounded-full px-0 sm:h-11 sm:w-auto sm:min-w-40 sm:justify-between sm:gap-2 sm:px-3 [&_[data-slot=select-indicator]]:hidden sm:[&_[data-slot=select-indicator]]:inline-flex",
      className,
    )}
    ref={ref}
    title={label}
    variant="compact"
    {...props}
  >
    <Icon className="sm:hidden" glyph={glyph} size={20} tone="secondary" />
    <SelectValue className="hidden sm:block" />
  </SelectTrigger>
));
CollectionToolbarSelectTrigger.displayName = "CollectionToolbarSelectTrigger";

export function CollectionToolbarStaticValue({
  glyph = SortIcon,
  label,
}: {
  glyph?: IconGlyph;
  label: string;
}) {
  return (
    <span
      className="border-line bg-surface flex size-11 shrink-0 items-center justify-center gap-0 rounded-full border px-0 text-sm sm:h-11 sm:w-auto sm:min-w-40 sm:justify-start sm:gap-2 sm:px-3"
      title={label}
    >
      <Icon className="sm:hidden" glyph={glyph} size={20} tone="secondary" />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </span>
  );
}
