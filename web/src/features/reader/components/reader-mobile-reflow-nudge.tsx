"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Button, IconButton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { DismissIcon, FitIcon } from "@/design-system/icons/semantic-icons";

export const readerMobileReflowNudgeKey =
  "scholens:reader-mobile-reflow-nudge:v1";

function nudgeDismissed() {
  try {
    return window.localStorage.getItem(readerMobileReflowNudgeKey) === "1";
  } catch {
    return false;
  }
}

function rememberNudge() {
  try {
    window.localStorage.setItem(readerMobileReflowNudgeKey, "1");
  } catch {
    // The Reader remains usable when a WebView denies persistent storage.
  }
}

export function useReaderMobileReflowNudge(eligible: boolean) {
  const storedDismissed = React.useSyncExternalStore(
    () => () => undefined,
    nudgeDismissed,
    () => true,
  );
  const [dismissed, setDismissed] = React.useState(false);

  const dismiss = React.useCallback(() => {
    rememberNudge();
    setDismissed(true);
  }, []);

  return { dismiss, visible: eligible && !storedDismissed && !dismissed };
}

export function ReaderMobileReflowNudge({
  onDismiss,
  onOpenReflow,
}: {
  onDismiss: () => void;
  onOpenReflow: () => void;
}) {
  const t = useTranslations("Reader.mobileReflowNudge");
  return (
    <aside className="border-line bg-subtle flex items-start gap-3 border-b px-3 py-3 lg:hidden">
      <span className="bg-surface grid size-9 shrink-0 place-items-center rounded-[var(--radius-lg)]">
        <Icon glyph={FitIcon} size={20} tone="secondary" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{t("title")}</p>
        <p className="text-secondary mt-0.5 text-xs leading-5">
          {t("description")}
        </p>
        <Button
          className="mt-2"
          onClick={onOpenReflow}
          size="sm"
          variant="secondary"
        >
          {t("open")}
        </Button>
      </div>
      <IconButton label={t("dismiss")} onClick={onDismiss} variant="ghost">
        <Icon glyph={DismissIcon} size={20} tone="secondary" />
      </IconButton>
    </aside>
  );
}
