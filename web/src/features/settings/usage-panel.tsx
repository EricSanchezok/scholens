"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncBoundary } from "@/components/feedback";
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { settingsQueries, type UsagePeriod } from "./api";
import { formatDateOnly, formatStorageKilobytes } from "./formatters";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsCardHeader,
  SettingsPanelHeader,
  SettingsStatus,
} from "./settings-layout";

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
    <div className="grid gap-2">
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
        className="bg-subtle h-2 overflow-hidden rounded-full"
        role="progressbar"
      >
        <div
          className="bg-primary h-full rounded-full transition-[width] motion-reduce:transition-none"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

export function UsagePanel() {
  const t = useTranslations("Settings");
  const format = useFormatter();
  const [period, setPeriod] = React.useState<UsagePeriod>("current_week");
  const usage = useQuery(settingsQueries.usage(period));

  return (
    <div>
      <SettingsPanelHeader
        description={t("usage.description")}
        title={t("usage.title")}
      />
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
            <div className="grid gap-5">
              <SettingsCard>
                <SettingsCardHeader
                  action={
                    <SettingsStatus tone="success">{planLabel}</SettingsStatus>
                  }
                  description={t("usage.planDescription")}
                  title={t("usage.plan")}
                />
                <SettingsCardBody>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-secondary text-sm">
                      {formatDateOnly(data.period_start, format.dateTime)}
                      {" – "}
                      {formatDateOnly(data.period_end, format.dateTime)}
                    </p>
                    <Select
                      onValueChange={(value) => setPeriod(value as UsagePeriod)}
                      value={period}
                    >
                      <SelectTrigger
                        aria-label={t("usage.periodLabel")}
                        className="w-44"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="current_week">
                          {t("usage.period.currentWeek")}
                        </SelectItem>
                        <SelectItem value="four_weeks">
                          {t("usage.period.fourWeeks")}
                        </SelectItem>
                        <SelectItem value="twelve_weeks">
                          {t("usage.period.twelveWeeks")}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="border-line mt-5 border-t pt-5">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        aria-label={`${t("usage.upgrade")}. ${t("usage.billingUnavailable")}`}
                        disabled
                      >
                        {t("usage.upgrade")}
                      </Button>
                      <Button
                        aria-label={`${t("usage.manageBilling")}. ${t("usage.billingUnavailable")}`}
                        disabled
                        variant="secondary"
                      >
                        {t("usage.manageBilling")}
                      </Button>
                    </div>
                    <p className="text-secondary mt-2 text-sm">
                      {t("usage.billingUnavailable")}
                    </p>
                  </div>
                </SettingsCardBody>
              </SettingsCard>

              <SettingsCard>
                <SettingsCardHeader title={t("usage.resources")} />
                <SettingsCardBody>
                  <div className="grid gap-6">
                    <UsageMeter
                      format={(value) => format.number(value, "compact")}
                      label={t("usage.tokenCredits")}
                      limit={data.usage.token_credits_limit}
                      used={data.usage.token_credits_used}
                    />
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
                    <div className="grid gap-1 text-sm">
                      <div className="flex items-center justify-between gap-4">
                        <span className="font-medium">
                          {t("usage.projectPapers")}
                        </span>
                        <span className="text-secondary tabular-nums">
                          {t("usage.projectPapersLimit", {
                            value: data.limits.project_papers,
                          })}
                        </span>
                      </div>
                      <p className="text-secondary text-xs leading-5">
                        {t("usage.projectPapersDescription")}
                      </p>
                    </div>
                    <UsageMeter
                      format={(value) =>
                        formatStorageKilobytes(value, format.number)
                      }
                      label={t("usage.storage")}
                      limit={data.limits.knowledge_base_size_kb}
                      used={data.usage.knowledge_base_size_kb}
                    />
                  </div>
                </SettingsCardBody>
              </SettingsCard>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
