"use client";

import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui";
import type { ReadingActivityPreferences } from "../types";

export function ReadingActivityPreferencesControl({
  error,
  onChange,
  pending,
  saved,
  value,
}: {
  error?: boolean;
  onChange: (value: ReadingActivityPreferences) => void;
  pending?: boolean;
  saved?: boolean;
  value: ReadingActivityPreferences;
}) {
  const t = useTranslations("ResearchActivity.preferences");
  return (
    <section aria-labelledby="reading-activity-settings-title">
      <h3
        className="text-sm font-semibold"
        id="reading-activity-settings-title"
      >
        {t("title")}
      </h3>
      <p className="text-muted mt-1 max-w-xl text-sm leading-6">
        {t("description")}
      </p>
      <div className="mt-3 grid max-w-2xl gap-1">
        <div className="hover:bg-hover flex min-h-16 items-center justify-between gap-4 rounded-[var(--radius-lg)] px-3 py-3">
          <span className="min-w-0">
            <span
              className="block text-sm font-medium"
              id="reading-activity-recording-label"
            >
              {t("recording")}
            </span>
            <span
              className="text-secondary mt-0.5 block text-xs leading-5"
              id="reading-activity-recording-description"
            >
              {t("recordingDescription")}
            </span>
          </span>
          <Switch
            aria-describedby="reading-activity-recording-description"
            aria-labelledby="reading-activity-recording-label"
            checked={value.recordingEnabled}
            disabled={pending}
            onCheckedChange={(checked) =>
              onChange({ ...value, recordingEnabled: checked })
            }
          />
        </div>
        <div className="hover:bg-hover flex min-h-16 items-center justify-between gap-4 rounded-[var(--radius-lg)] px-3 py-3">
          <span className="min-w-0">
            <span
              className="block text-sm font-medium"
              id="reading-activity-project-label"
            >
              {t("project")}
            </span>
            <span
              className="text-secondary mt-0.5 block text-xs leading-5"
              id="reading-activity-project-description"
            >
              {t("projectDescription")}
            </span>
          </span>
          <Switch
            aria-describedby="reading-activity-project-description"
            aria-labelledby="reading-activity-project-label"
            checked={value.contributeAnonymousProjectAggregates}
            disabled={pending}
            onCheckedChange={(checked) =>
              onChange({
                ...value,
                contributeAnonymousProjectAggregates: checked,
              })
            }
          />
        </div>
      </div>
      <p
        aria-live="polite"
        className="text-muted mt-2 min-h-5 text-xs"
        role="status"
      >
        {pending
          ? t("saving")
          : error
            ? t("saveError")
            : saved
              ? t("saved")
              : ""}
      </p>
    </section>
  );
}
