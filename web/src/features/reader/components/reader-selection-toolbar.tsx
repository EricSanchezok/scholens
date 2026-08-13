"use client";

import {
  AskIcon,
  SuccessIcon,
  HighlightColorIcon,
  CopyIcon,
  AddAnnotationIcon,
  ErrorIcon,
} from "@/design-system/icons/semantic-icons";
import * as React from "react";

import { useCopyActionFeedback } from "@/components/feedback";
import {
  IconButton,
  keyboardFocusRing,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import type { ReaderSelection } from "./pdf-page";

export type ReaderSelectionLabels = {
  ask: string;
  comment: string;
  copy: string;
  copied: string;
  copying: string;
  copyFailed: string;
  highlight: string;
  colors: Record<"yellow" | "blue" | "green" | "neutral", string>;
};

const colorClasses = {
  yellow: "bg-state-warning-bg",
  blue: "bg-state-info-bg",
  green: "bg-state-success-bg",
  neutral: "bg-accent",
} as const;

const floatingSurfaceClass =
  "border-line bg-elevated text-foreground shadow-raised relative isolate z-[1] flex overflow-hidden rounded-full border opacity-100";

function ToolbarAction({
  children,
  disabled,
  label,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          className="size-9 min-h-9 rounded-full"
          disabled={disabled}
          label={label}
          onClick={onClick}
          variant="ghost"
        >
          {children}
        </IconButton>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function ReaderSelectionToolbar({
  labels,
  onAsk,
  onComment,
  onCopySettled,
  onHighlight,
  selection,
}: {
  labels: ReaderSelectionLabels;
  onAsk: () => void;
  onComment: () => void;
  onCopySettled: () => void;
  onHighlight: (color: keyof typeof colorClasses) => void;
  selection: ReaderSelection;
}) {
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const copyFeedback = useCopyActionFeedback({
    labels: {
      idle: labels.copy,
      pending: labels.copying,
      success: labels.copied,
      error: labels.copyFailed,
    },
    value: selection.selected_text,
  });
  const rects =
    selection.anchor.kind === "pdf_text" ? selection.anchor.rects : [];
  const bounds = rects.reduce(
    (current, rect) => ({
      left: Math.min(current.left, rect.x),
      right: Math.max(current.right, rect.x + rect.width),
      top: Math.min(current.top, rect.y),
      bottom: Math.max(current.bottom, rect.y + rect.height),
    }),
    { left: 1, right: 0, top: 1, bottom: 0 },
  );
  const spaceAbove = bounds.top;
  const spaceBelow = 1 - bounds.bottom;
  const showBelow = spaceAbove < 0.08 || spaceBelow > spaceAbove;
  const left = Math.min(0.88, Math.max(0.12, (bounds.left + bounds.right) / 2));

  async function copySelection() {
    await copyFeedback.copy().catch(() => undefined);
    window.setTimeout(onCopySettled, 900);
  }

  const feedbackGlyph =
    copyFeedback.status === "success"
      ? SuccessIcon
      : copyFeedback.status === "error"
        ? ErrorIcon
        : CopyIcon;

  return (
    <TooltipProvider delayDuration={350}>
      <div
        className="pointer-events-auto absolute isolate z-40 flex flex-col items-center gap-1"
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onPointerUp={(event) => event.stopPropagation()}
        style={{
          left: `${left * 100}%`,
          top: `${(showBelow ? bounds.bottom : bounds.top) * 100}%`,
          transform: `${showBelow ? "translateY(0.5rem)" : "translateY(calc(-100% - 0.5rem))"} translateX(-50%)`,
        }}
      >
        <div
          className={cn(floatingSurfaceClass, "gap-0.5 p-1")}
          data-reader-selection-toolbar-surface="actions"
          style={{ backgroundColor: "var(--color-bg-elevated)" }}
        >
          <ToolbarAction label={labels.ask} onClick={onAsk}>
            <Icon glyph={AskIcon} size={20} />
          </ToolbarAction>
          <ToolbarAction
            label={labels.highlight}
            onClick={() => setPaletteOpen((open) => !open)}
          >
            <Icon glyph={HighlightColorIcon} size={20} />
          </ToolbarAction>
          <ToolbarAction label={labels.comment} onClick={onComment}>
            <Icon glyph={AddAnnotationIcon} size={20} />
          </ToolbarAction>
          <ToolbarAction
            disabled={copyFeedback.status === "pending"}
            label={copyFeedback.label}
            onClick={() => void copySelection()}
          >
            <Icon glyph={feedbackGlyph} size={20} />
          </ToolbarAction>
          <span aria-live="polite" className="sr-only">
            {copyFeedback.feedbackVisible ? copyFeedback.label : ""}
          </span>
        </div>
        {paletteOpen ? (
          <div
            aria-label={labels.highlight}
            className={cn(floatingSurfaceClass, "gap-2 p-2")}
            data-reader-selection-toolbar-surface="palette"
            role="group"
            style={{ backgroundColor: "var(--color-bg-elevated)" }}
          >
            {(
              Object.keys(colorClasses) as Array<keyof typeof colorClasses>
            ).map((color) => (
              <button
                aria-label={labels.colors[color]}
                className={cn(
                  "border-control size-6 rounded-full border transition-transform hover:scale-110 motion-reduce:transition-none",
                  keyboardFocusRing,
                  colorClasses[color],
                )}
                key={color}
                onClick={() => onHighlight(color)}
                type="button"
              />
            ))}
          </div>
        ) : null}
      </div>
    </TooltipProvider>
  );
}
