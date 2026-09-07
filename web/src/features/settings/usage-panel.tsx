"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { AsyncBoundary } from "@/components/feedback";
import { settingsQueries } from "./api";
import { formatStorageKilobytes } from "./formatters";
import { SettingsPanelHeader, SettingsStatus } from "./settings-layout";

function UsageMeter({
  label,
  used,
  limit,
  format,
}: {
  label: string;
  used: number;
  limit: number;
  format: (value: number) => string;
}) {
  const percent =
    limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="grid gap-2.5 py-3">
      <div className="flex items-center justify-between gap-4 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-secondary tabular-nums">
          {format(used)} / {format(limit)}
        </span>
      </div>
      <div
        aria-label={label}
        aria-valuemax={limit}
        aria-valuemin={0}
        aria-valuenow={used}
        className="bg-subtle h-1.5 overflow-hidden rounded-full"
        role="progressbar"
      >
        <div
          className="motion-progress bg-primary h-full w-full rounded-full"
          style={{ transform: `scaleX(${percent / 100})` }}
        />
      </div>
    </div>
  );
}

export function UsagePanel({ showHeader = true }: { showHeader?: boolean }) {
  const t = useTranslations("Settings");
  const format = useFormatter();
  const usage = useQuery(settingsQueries.usage());

  return (
    <div>
      {showHeader ? (
        <SettingsPanelHeader
          description={t("usage.description")}
          title={t("usage.title")}
        />
      ) : null}
      <AsyncBoundary
        data={usage.data}
        error={usage.error}
        loading={usage.isLoading}
        retry={() => void usage.refetch()}
      >
        {(data) => {
          const planLabel =
            data.plan === "researcher"
              ? t("plan.researcher")
              : data.plan === "basic"
                ? t("plan.basic")
                : data.plan;
          return (
            <div className="grid max-w-2xl gap-8">
              <section className="bg-subtle rounded-[var(--radius-xl)] px-5 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-semibold">{t("usage.plan")}</h3>
                    <p className="text-secondary mt-1 text-sm leading-5">
                      {t("usage.planDescription")}
                    </p>
                  </div>
                  <SettingsStatus tone="success">{planLabel}</SettingsStatus>
                </div>
              </section>

              <section aria-labelledby="usage-resources-title">
                <h3
                  className="text-sm font-semibold"
                  id="usage-resources-title"
                >
                  {t("usage.resources")}
                </h3>
                <div className="divide-line-subtle mt-2 divide-y">
                  <UsageMeter
                    format={(value) => format.number(value)}
                    label={t("usage.papers")}
                    limit={data.limits.paper_uploads}
                    used={data.usage.paper_uploads}
                  />
                  <UsageMeter
                    format={(value) => format.number(value)}
                    label={t("usage.projects")}
                    limit={data.limits.projects}
                    used={data.usage.projects}
                  />
                  <UsageMeter
                    format={(value) =>
                      formatStorageKilobytes(value, format.number)
                    }
                    label={t("usage.storage")}
                    limit={data.limits.knowledge_base_size_kb}
                    used={data.usage.knowledge_base_size_kb}
                  />
                </div>
              </section>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
