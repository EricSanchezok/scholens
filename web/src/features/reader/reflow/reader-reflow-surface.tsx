"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useToast } from "@/components/ui";
import { reflowKeys, reflowQueries, retryDocumentReflow } from "./api";
import { ReaderReflowView } from "./reader-reflow-view";
import { useReflowTranslations } from "./use-reflow-translations";

export function ReaderReflowSurface({
  documentId,
  fullTranslationEnabled,
  onFullTranslationEnabledChange,
  onOpenPdfPage,
  targetLanguage,
  title,
  translationCacheVersion,
}: {
  documentId: string;
  fullTranslationEnabled: boolean;
  onFullTranslationEnabledChange: (enabled: boolean) => void;
  onOpenPdfPage: (page: number) => void;
  targetLanguage: string;
  title: string;
  translationCacheVersion?: string;
}) {
  const queryClient = useQueryClient();
  const t = useTranslations("Reader.reflow");
  const toast = useToast();
  const reflowQuery = useQuery(reflowQueries.document(documentId, true));
  const translations = useReflowTranslations({
    cacheVersion: translationCacheVersion,
    documentId,
    enabled:
      fullTranslationEnabled &&
      translationCacheVersion !== undefined &&
      reflowQuery.data?.status === "completed",
  });

  const retry = React.useCallback(async () => {
    try {
      const result = await retryDocumentReflow(documentId);
      queryClient.setQueryData(reflowKeys.document(documentId), result);
    } catch {
      toast.notify({
        description: t("retryFailedDescription"),
        title: t("retryFailedTitle"),
      });
    }
  }, [documentId, queryClient, t, toast]);

  if (reflowQuery.isPending) {
    return (
      <div className="m-auto w-full max-w-sm p-6">
        <LoadingState label={t("loading")} />
      </div>
    );
  }
  if (
    reflowQuery.data?.status === "pending" ||
    reflowQuery.data?.status === "processing"
  ) {
    return (
      <div className="m-auto w-full max-w-md p-6">
        <AsyncFeedback
          description={t("processingDescription")}
          state="loading"
          title={t("processingTitle")}
        />
      </div>
    );
  }
  if (reflowQuery.isError || reflowQuery.data?.status === "failed") {
    return (
      <div className="m-auto w-full max-w-md p-6">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: () => void retry() }}
          description={t("failedDescription")}
          state="error"
          title={t("failedTitle")}
        />
      </div>
    );
  }
  if (reflowQuery.data?.status !== "completed") return null;

  return (
    <ReaderReflowView
      blocks={reflowQuery.data.blocks}
      fullTranslationEnabled={fullTranslationEnabled}
      labels={{
        document: t("document"),
        figurePlaceholder: t("figurePlaceholder"),
        fullTranslation: t("fullTranslation"),
        fullTranslationDescription: t("fullTranslationDescription"),
        openPdfPage: (page) => t("openPdfPage", { page }),
        original: t("original"),
        retryTranslation: t("retryTranslation"),
        translated: t("translated"),
        translating: t("translating"),
        translationFailed: t("translationFailed"),
      }}
      onFullTranslationEnabledChange={onFullTranslationEnabledChange}
      onOpenPdfPage={onOpenPdfPage}
      onRequestTranslation={translations.request}
      onRetryTranslation={translations.retry}
      targetLanguage={targetLanguage}
      title={title}
      translations={translations.translations}
    />
  );
}
