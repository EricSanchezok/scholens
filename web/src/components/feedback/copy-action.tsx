"use client";

import { Check, Copy, WarningCircle } from "iconoir-react";

import { TransientActionIconButton } from "./transient-action";

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
      action={() => navigator.clipboard.writeText(value)}
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
