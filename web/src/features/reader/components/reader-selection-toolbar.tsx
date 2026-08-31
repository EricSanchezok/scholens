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
  focusSurfaceVariants,
  IconButton,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { AnimatePresence, m, motionVariants } from "@/design-system/motion";
import { cn } from "@/lib/utilities/cn";
import { useReaderMediaQuery } from "../hooks/use-reader-layout";
import {
  readerHighlightColors,
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
import { ReaderHighlightColorButton } from "./reader-highlight-color-button";

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
  const showTranslationPreview = useReaderMediaQuery("(min-width: 64rem)");
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
  const placementKey = JSON.stringify({
    anchor: selection.anchor,
    documentId: selection.document_id,
    pageNumber: selection.page_number,
    selectedText: selection.selected_text,
  });
  const { floatingRef, measureRef, position } = useReaderFloatingPosition({
    boundaryRef,
    bounds,
    placementKey,
    preferredPlacement: "bottom",
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
        className="pointer-events-auto absolute isolate z-40 flex min-w-0 flex-col items-center gap-1"
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
          visibility: position && position.visible ? "visible" : "hidden",
        }}
        variants={motionVariants.swap}
      >
        <div
          className={cn(floatingSurfaceClass, "gap-0.5 p-1")}
          data-reader-selection-toolbar-surface="actions"
          ref={measureRef}
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
          {translationPreview && showTranslationPreview ? (
            <m.div
              animate="animate"
              aria-busy={translationPreview.status === "streaming"}
              aria-label={labels.viewTranslation}
              className="border-line bg-elevated shadow-raised hidden w-[clamp(22.5rem,26vw,30rem)] max-w-full min-w-0 overflow-hidden rounded-[var(--radius-lg)] border p-3 text-left lg:block"
              data-reader-selection-translation-preview
              exit="exit"
              initial="initial"
              role="group"
              style={{ maxWidth: position?.maxWidth }}
              variants={motionVariants.swap}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted block text-xs font-medium">
                  {translationPreview.status === "streaming"
                    ? labels.translating
                    : translationPreview.status === "error"
                      ? labels.translationFailed
                      : labels.viewTranslation}
                </span>
                <IconButton
                  className="size-7 min-h-7 rounded-full"
                  label={labels.viewTranslation}
                  onClick={onOpenTranslation}
                  variant="ghost"
                >
                  <Icon glyph={TranslationIcon} size={16} />
                </IconButton>
              </div>
              <div
                aria-label={labels.viewTranslation}
                className={cn(
                  "mt-2 block max-h-[min(24rem,40dvh)] min-w-0 overflow-y-auto overscroll-contain text-sm leading-6 [overflow-wrap:anywhere]",
                  focusSurfaceVariants({ intent: "scroll" }),
                )}
                data-reader-selection-translation-text
                role="region"
                style={{
                  maxHeight: position
                    ? `min(24rem, 40dvh, max(0px, calc(${Math.max(0, position.contentMaxHeight)}px - 4rem)))`
                    : undefined,
                }}
                tabIndex={0}
              >
                {translationPreview.text ||
                  (translationPreview.status === "error"
                    ? translationError(
                        translationErrorMessageKey(
                          translationPreview.errorCode,
                        ),
                      )
                    : labels.translating)}
              </div>
              <span
                aria-atomic="true"
                aria-live="polite"
                className="sr-only"
                role="status"
              >
                {translationPreview.status === "streaming"
                  ? labels.translating
                  : translationPreview.status === "error"
                    ? labels.translationFailed
                    : labels.viewTranslation}
              </span>
            </m.div>
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
                        focusSurfaceVariants({ intent: "selection" }),
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
              <div
                className="grid grid-cols-4 gap-2"
                data-reader-highlight-palette=""
              >
                {readerHighlightColors.map((color) => (
                  <ReaderHighlightColorButton
                    className="hover:scale-105"
                    color={color}
                    key={color}
                    label={labels.colors[color]}
                    onClick={() => onHighlight(color, audience)}
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
