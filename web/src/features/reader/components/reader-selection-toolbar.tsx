"use client";

import {
  AskIcon,
  SuccessIcon,
  HighlightColorIcon,
  CopyIcon,
  AddAnnotationIcon,
  ErrorIcon,
  TranslationIcon,
} from "@/design-system/icons/semantic-icons";
import * as React from "react";
import { useTranslations } from "next-intl";

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
import { AnimatePresence, m, motionVariants } from "@/design-system/motion";
import { cn } from "@/lib/utilities/cn";
import {
  readerHighlightColors,
  readerHighlightColorValue,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";
import { readerPdfRectsForPage } from "../reader-pdf-position";
import {
  readerSelectionFocusPage,
  type ReaderSelection,
} from "../reader-selection";
import type { ReaderAnnotationAudience } from "../reader-types";
import { useReaderFloatingPosition } from "./use-reader-floating-position";
import { translationErrorMessageKey } from "../translation/translation-errors";

export type ReaderSelectionLabels = {
  ask: string;
  comment: string;
  copy: string;
  copied: string;
  copying: string;
  copyFailed: string;
  highlight: string;
  personal: string;
  project: string;
  translate: string;
  translating: string;
  translationFailed: string;
  viewTranslation: string;
  colors: Record<ReaderHighlightColor, string>;
};

export type ReaderSelectionTranslationPreview = {
  status: "streaming" | "completed" | "error";
  text: string;
  errorCode?: string;
};

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
  onOpenTranslation,
  onTranslate,
  boundaryRef,
  projectContext,
  selection,
  translationPreview,
}: {
  labels: ReaderSelectionLabels;
  onAsk: () => void;
  onComment: () => void;
  onCopySettled: () => void;
  onHighlight: (
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => void;
  onOpenTranslation: () => void;
  onTranslate: () => void;
  boundaryRef?: React.RefObject<HTMLElement | null>;
  projectContext?: boolean;
  selection: ReaderSelection;
  translationPreview?: ReaderSelectionTranslationPreview;
}) {
  const translationError = useTranslations("Reader.translation");
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [audience, setAudience] =
    React.useState<ReaderAnnotationAudience>("personal");
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
    selection.anchor.kind === "pdf_text"
      ? (readerPdfRectsForPage(
          selection.anchor,
          readerSelectionFocusPage(selection),
        ) ?? selection.anchor.rects)
      : [];
  const bounds = rects.reduce(
    (current, rect) => ({
      left: Math.min(current.left, rect.x),
      right: Math.max(current.right, rect.x + rect.width),
      top: Math.min(current.top, rect.y),
      bottom: Math.max(current.bottom, rect.y + rect.height),
    }),
    { left: 1, right: 0, top: 1, bottom: 0 },
  );
  const { floatingRef, position } = useReaderFloatingPosition({
    boundaryRef,
    bounds,
  });

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
      <m.div
        animate="animate"
        className="pointer-events-auto absolute isolate z-40 flex flex-col items-center gap-1 overflow-y-auto overscroll-contain"
        data-reader-selection-floating
        data-reader-selection-placement={position?.placement}
        initial="initial"
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onPointerUp={(event) => event.stopPropagation()}
        ref={floatingRef}
        style={{
          left: position?.left ?? 0,
          maxHeight: position?.maxHeight,
          maxWidth: position?.maxWidth,
          top: position?.top ?? 0,
          visibility: position ? "visible" : "hidden",
        }}
        variants={motionVariants.swap}
      >
        <div
          className={cn(floatingSurfaceClass, "gap-0.5 p-1")}
          data-reader-selection-toolbar-surface="actions"
          style={{ backgroundColor: "var(--color-bg-elevated)" }}
        >
          <ToolbarAction label={labels.ask} onClick={onAsk}>
            <Icon glyph={AskIcon} size={20} />
          </ToolbarAction>
          <ToolbarAction label={labels.translate} onClick={onTranslate}>
            <Icon glyph={TranslationIcon} size={20} />
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
        <AnimatePresence initial={false}>
          {translationPreview ? (
            <m.button
              animate="animate"
              aria-label={labels.viewTranslation}
              className={cn(
                "border-line bg-elevated shadow-raised hidden w-80 max-w-[min(20rem,80vw)] rounded-[var(--radius-lg)] border p-3 text-left lg:block",
                keyboardFocusRing,
              )}
              data-reader-selection-translation-preview
              exit="exit"
              initial="initial"
              onClick={onOpenTranslation}
              type="button"
              variants={motionVariants.swap}
            >
              <span className="text-muted block text-xs font-medium">
                {translationPreview.status === "streaming"
                  ? labels.translating
                  : translationPreview.status === "error"
                    ? labels.translationFailed
                    : labels.viewTranslation}
              </span>
              <span
                className="mt-1 line-clamp-4 block text-sm leading-6"
                data-reader-selection-translation-text
              >
                {translationPreview.text ||
                  (translationPreview.status === "error"
                    ? translationError(
                        translationErrorMessageKey(
                          translationPreview.errorCode,
                        ),
                      )
                    : labels.translating)}
              </span>
            </m.button>
          ) : null}
          {paletteOpen ? (
            <m.div
              animate="animate"
              aria-label={labels.highlight}
              className={cn(
                floatingSurfaceClass,
                "flex-col gap-2 rounded-[var(--radius-lg)] p-2",
              )}
              data-reader-selection-toolbar-surface="palette"
              exit="exit"
              initial="initial"
              role="group"
              style={{ backgroundColor: "var(--color-bg-elevated)" }}
              variants={motionVariants.swap}
            >
              {projectContext ? (
                <div className="bg-subtle grid w-full grid-cols-2 rounded-[var(--radius-md)] p-0.5 text-xs">
                  {(["personal", "project"] as const).map((value) => (
                    <button
                      aria-pressed={audience === value}
                      className={cn(
                        "rounded-[calc(var(--radius-md)-2px)] px-2 py-1",
                        audience === value && "bg-surface shadow-raised",
                        keyboardFocusRing,
                      )}
                      key={value}
                      onClick={() => setAudience(value)}
                      type="button"
                    >
                      {labels[value]}
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="flex gap-2">
                {readerHighlightColors.map((color) => (
                  <button
                    aria-label={labels.colors[color]}
                    className={cn(
                      "motion-control border-control size-6 rounded-full border hover:scale-105",
                      keyboardFocusRing,
                    )}
                    key={color}
                    onClick={() => onHighlight(color, audience)}
                    style={{
                      backgroundColor: readerHighlightColorValue(color),
                    }}
                    type="button"
                  />
                ))}
              </div>
            </m.div>
          ) : null}
        </AnimatePresence>
      </m.div>
    </TooltipProvider>
  );
}
