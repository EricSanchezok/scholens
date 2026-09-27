"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useSettingsLauncher } from "@/features/settings";
import { ApiError } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { readerKeys, readerQueries, retryReaderStage } from "./api/queries";
import { ReaderProcessingStatus } from "./components/reader-processing-status";

export function ReaderProcessing({ documentId }: { documentId: string }) {
  const t = useTranslations("Reader.processingStages");
  const client = useQueryClient();
  const { openSection } = useSettingsLauncher();
  const query = useQuery(readerQueries.processing(documentId));
  const completed = query.data?.stages
    .filter((stage) => stage.status === "completed")
    .map((stage) => `${stage.stage}:${stage.job_id}`)
    .join(",");
  const observed = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (!completed || observed.current === completed) return;
    observed.current = completed;
    void client.invalidateQueries({
      queryKey: readerKeys.document(documentId),
    });
    void client.invalidateQueries({
      queryKey: readerKeys.annotationLists(documentId),
    });
  }, [client, completed, documentId]);
  const retry = useMutation({
    mutationFn: (stage: components["schemas"]["DocumentStageStatus"]) =>
      retryReaderStage(documentId, {
        stage: stage.stage,
        job_id: stage.job_id!,
        acknowledge_provider_charge: stage.stage === "enrichment",
      }),
    onSettled: () =>
      client.invalidateQueries({ queryKey: readerKeys.processing(documentId) }),
  });
  const error = retry.error;
  const retryError = error
    ? `${t(error instanceof ApiError && error.status === 409 ? "changed" : "retryFailed")}${error instanceof ApiError && error.correlationId ? ` (${error.correlationId})` : ""}`
    : undefined;
  return (
    <ReaderProcessingStatus
      onConnect={() => openSection("connections")}
      onRefresh={() => void query.refetch()}
      onRetry={(stage) => {
        if (stage.job_id) retry.mutate(stage);
      }}
      retryError={retryError}
      retrying={
        retry.isPending ? (retry.variables?.job_id ?? undefined) : undefined
      }
      stages={query.data?.stages}
      unavailable={query.isError}
    />
  );
}
