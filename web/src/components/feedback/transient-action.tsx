"use client";

import * as React from "react";

import {
  IconButton,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";

export type TransientActionStatus = "idle" | "pending" | "success" | "error";

export type TransientActionLabels = {
  idle: string;
  pending: string;
  success: string;
  error: string;
};

const DEFAULT_FEEDBACK_DURATION = 1600;

export function useTransientActionFeedback({
  duration = DEFAULT_FEEDBACK_DURATION,
}: {
  duration?: number;
} = {}) {
  const [status, setStatus] = React.useState<TransientActionStatus>("idle");
  const resetTimer = React.useRef<number | null>(null);
  const operation = React.useRef(0);

  const clearResetTimer = React.useCallback(() => {
    if (resetTimer.current !== null) {
      window.clearTimeout(resetTimer.current);
      resetTimer.current = null;
    }
  }, []);

  React.useEffect(() => clearResetTimer, [clearResetTimer]);

  const run = React.useCallback(
    async (action: () => void | Promise<void>) => {
      clearResetTimer();
      const currentOperation = ++operation.current;
      setStatus("pending");

      try {
        await action();
        if (operation.current !== currentOperation) return;
        setStatus("success");
      } catch (error) {
        if (operation.current !== currentOperation) throw error;
        setStatus("error");
        resetTimer.current = window.setTimeout(
          () => setStatus("idle"),
          duration,
        );
        throw error;
      }

      resetTimer.current = window.setTimeout(() => setStatus("idle"), duration);
    },
    [clearResetTimer, duration],
  );

  return { run, status };
}

export function TransientActionIconButton({
  action,
  className,
  disabled,
  errorGlyph,
  glyph,
  labels,
  onError,
  onSuccess,
  successGlyph,
  iconSize = 20,
}: {
  action: () => void | Promise<void>;
  className?: string;
  disabled?: boolean;
  errorGlyph: IconGlyph;
  glyph: IconGlyph;
  labels: TransientActionLabels;
  onError?: (error: unknown) => void;
  onSuccess?: () => void;
  successGlyph: IconGlyph;
  iconSize?: 16 | 20 | 24;
}) {
  const { run, status } = useTransientActionFeedback();
  const [tooltipRequested, setTooltipRequested] = React.useState(false);
  const label = labels[status];
  const feedbackVisible = status === "success" || status === "error";
  const tooltipOpen = feedbackVisible || tooltipRequested;
  const Glyph =
    status === "success"
      ? successGlyph
      : status === "error"
        ? errorGlyph
        : glyph;

  return (
    <>
      <TooltipProvider delayDuration={350}>
        <Tooltip
          onOpenChange={(open) => {
            if (!feedbackVisible) setTooltipRequested(open);
          }}
          open={tooltipOpen}
        >
          <TooltipTrigger asChild>
            <IconButton
              aria-busy={status === "pending" || undefined}
              className={className}
              disabled={disabled || status === "pending"}
              label={label}
              onClick={() => {
                void run(action).then(
                  () => onSuccess?.(),
                  (error) => onError?.(error),
                );
              }}
              variant="ghost"
            >
              <Icon
                className="motion-icon"
                glyph={Glyph}
                size={iconSize}
                tone="secondary"
              />
            </IconButton>
          </TooltipTrigger>
          <TooltipContent side="bottom">{label}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <span aria-live="polite" className="sr-only">
        {feedbackVisible ? label : ""}
      </span>
    </>
  );
}
