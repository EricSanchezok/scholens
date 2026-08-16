"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button, Progress } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import {
  cancelZoteroImport,
  type ZoteroOperation,
  zoteroKeys,
  zoteroQueries,
} from "./api";
import { zoteroOperationErrorKey } from "./message-keys";

export function ZoteroOperationStatus({
  initialOperation,
  operationId,
  onComplete,
  onDismiss,
}: {
  initialOperation?: ZoteroOperation;
  operationId: string;
  onComplete: () => void;
  onDismiss: () => void;
}) {
  const t = useTranslations("Zotero.operation");
  const queryClient = useQueryClient();
  const operation = useQuery({
    ...zoteroQueries.operation("import", operationId),
    initialData: initialOperation,
  });
  const cancel = useMutation({
    mutationFn: () => cancelZoteroImport(operationId),
    onSuccess: async (result) => {
      queryClient.setQueryData(
        zoteroKeys.operation("import", operationId),
        result,
      );
      await queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
    },
  });
  const value = operation.data;
  const terminal = value
    ? ["partial", "succeeded", "failed", "cancelled"].includes(value.status)
    : false;
  const completionNotified = React.useRef(false);

  React.useEffect(() => {
    if (!terminal || completionNotified.current) return;
    completionNotified.current = true;
    onComplete();
  }, [onComplete, terminal]);

  if (!value) {
    return (
      <section
        aria-label={t("label")}
        className="border-line bg-subtle mt-4 rounded-[var(--radius-lg)] border p-4"
      >
        <p className="text-secondary text-sm" role="status">
          {t("loading")}
        </p>
      </section>
    );
  }
  const completed =
    value.counts.succeeded + value.counts.failed + value.counts.skipped;
  const percent = value.counts.total
    ? Math.round((completed / value.counts.total) * 100)
    : value.status === "succeeded"
      ? 100
      : 0;

  return (
    <section
      aria-label={t("label")}
      className="border-line bg-subtle mt-4 grid gap-3 rounded-[var(--radius-lg)] border p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{t(`status.${value.status}`)}</p>
          {!terminal && value.progress_code ? (
            <p className="text-secondary mt-1 text-sm" role="status">
              {t(`stage.${value.progress_code}`)}
            </p>
          ) : null}
          <p className="text-secondary mt-1 text-sm">
            {t("counts", {
              failed: value.counts.failed,
              succeeded: value.counts.succeeded,
              total: value.counts.total,
            })}
          </p>
        </div>
        {terminal ? (
          <Button onClick={onDismiss} size="sm" variant="ghost">
            {t("dismiss")}
          </Button>
        ) : (
          <Button
            loading={cancel.isPending}
            onClick={() => cancel.mutate()}
            size="sm"
            variant="ghost"
          >
            {t("cancel")}
          </Button>
        )}
      </div>
      {terminal ? (
        <Progress aria-label={t("progress")} value={percent} />
      ) : null}
      {cancel.isError ? (
        <p className="text-danger text-sm" role="alert">
          {t(
            zoteroOperationErrorKey(
              cancel.error instanceof ApiError && cancel.error.code
                ? cancel.error.code
                : "zotero_import_failed",
            ),
          )}
        </p>
      ) : null}
      {(value.items?.length ?? 0) > 0 && terminal ? (
        <ul className="grid gap-1 text-sm">
          {(value.items ?? [])
            .filter((item) => item.status === "failed")
            .slice(0, 3)
            .map((item) => (
              <li className="text-danger" key={item.zotero_item_key}>
                {t("itemFailed", {
                  error: t(
                    zoteroOperationErrorKey(
                      item.error_code ?? "zotero_import_failed",
                    ),
                  ),
                  title: item.title ?? item.zotero_item_key,
                })}
              </li>
            ))}
        </ul>
      ) : null}
    </section>
  );
}
