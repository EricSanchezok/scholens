"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { focusSurfaceVariants } from "@/components/ui/focus";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

type Stage = components["schemas"]["DocumentStageStatus"];

export function ReaderProcessingStatus({
  stages,
  unavailable,
  retrying,
  retryError,
  onRefresh,
  onRetry,
  onConnect,
}: {
  stages?: Stage[];
  unavailable?: boolean;
  retrying?: string;
  retryError?: string;
  onRefresh: () => void;
  onRetry: (stage: Stage) => void;
  onConnect: () => void;
}) {
  const t = useTranslations("Reader.processingStages");
  const active = stages?.some(
    (stage) => stage.status === "pending" || stage.status === "running",
  );
  const failed = stages?.some(
    (stage) =>
      stage.status === "failed" ||
      stage.status === "cancelled" ||
      stage.status === "stale",
  );
  return (
    <details className="border-line bg-surface shrink-0 border-b text-sm">
      <summary
        className={cn(
          focusSurfaceVariants(),
          "flex min-h-11 cursor-pointer items-center gap-2 px-4",
        )}
      >
        <span className="truncate">
          {t(
            unavailable
              ? "unavailable"
              : !stages
                ? "checking"
                : failed
                  ? "attention"
                  : active
                    ? "working"
                    : "ready",
          )}
        </span>
        <span className="text-muted ml-auto shrink-0">{t("details")}</span>
      </summary>
      <div className="grid max-h-64 gap-3 overflow-auto px-4 pb-3">
        <p className="text-muted">{t("description")}</p>
        {unavailable ? (
          <Button onClick={onRefresh} size="sm" variant="secondary">
            {t("refresh")}
          </Button>
        ) : null}
        <ul className="grid gap-2">
          {stages?.map((stage) => (
            <li className="flex flex-wrap items-center gap-2" key={stage.stage}>
              <span className="font-medium">{t(`name.${stage.stage}`)}</span>
              <span className="text-muted" role="status">
                {stage.required_integration
                  ? t("connectionRequired")
                  : t(`status.${stage.status}`)}
              </span>
              {stage.required_integration ? (
                <Button onClick={onConnect} size="sm" variant="secondary">
                  {t("connect")}
                </Button>
              ) : null}
              {stage.can_retry ? (
                <Button
                  disabled={Boolean(retrying)}
                  loading={retrying === stage.job_id}
                  onClick={() => onRetry(stage)}
                  size="sm"
                  variant="secondary"
                >
                  {t(stage.stage === "enrichment" ? "retryPaid" : "retry")}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {stages?.some(
          (stage) => stage.stage === "enrichment" && stage.can_retry,
        ) ? (
          <p className="text-muted">{t("paidNotice")}</p>
        ) : null}
        {retryError ? <p role="alert">{retryError}</p> : null}
      </div>
    </details>
  );
}
