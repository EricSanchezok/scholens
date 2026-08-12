"use client";

import { Check, Copy, WarningCircle } from "iconoir-react";
import * as React from "react";

import {
  TransientActionIconButton,
  type TransientActionLabels,
  useTransientActionFeedback,
} from "./transient-action";

function writeClipboardText(value: string) {
  return navigator.clipboard.writeText(value);
}

export function useCopyActionFeedback({
  labels,
  value,
}: {
  labels: TransientActionLabels;
  value: string;
}) {
  const { run, status } = useTransientActionFeedback();
  const copy = React.useCallback(
    () => run(() => writeClipboardText(value)),
    [run, value],
  );

  return {
    copy,
    feedbackVisible: status === "success" || status === "error",
    label: labels[status],
    status,
  };
}

export function CopyActionButton({
  className,
  errorLabel,
  pendingLabel,
  successLabel,
  value,
  label,
}: {
  className?: string;
  errorLabel: string;
  pendingLabel: string;
  successLabel: string;
  value: string;
  label: string;
}) {
  return (
    <TransientActionIconButton
      action={() => writeClipboardText(value)}
      className={className}
      errorGlyph={WarningCircle}
      glyph={Copy}
      labels={{
        idle: label,
        pending: pendingLabel,
        success: successLabel,
        error: errorLabel,
      }}
      successGlyph={Check}
    />
  );
}
