"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useToast } from "@/components/ui";
import { reflowKeys, reflowQueries, retryDocumentReflow } from "./api";
import {
  isTranslatableReflowBlock,
  ReaderReflowView,
  reflowMarkdownPlainText,
} from "./reader-reflow-view";
import { useReflowTranslations } from "./use-reflow-translations";
import type {
  FullTranslationStatus,
  TranslationPreferences,
} from "../translation";

export type ReaderReflowOutlineItem = {
  id: string;
  label: string;
};

export function ReaderReflowSurface({
  documentId,
  fullTranslationEnabled,
  onOutlineChange,
  onOpenPdfPage,
  onTranslationStatusChange,
  preferences,
  targetLanguage,
  translationCacheVersion,
}: {
  documentId: string;
  fullTranslationEnabled: boolean;
  onOutlineChange?: (items: ReaderReflowOutlineItem[]) => void;
  onOpenPdfPage: (page: number) => void;
  onTranslationStatusChange?: (status: FullTranslationStatus) => void;
  preferences?: TranslationPreferences;
  targetLanguage: string;
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
  const completedReflow =
    reflowQuery.data?.status === "completed" ? reflowQuery.data : undefined;
  const translateReferences = preferences?.translate_references ?? false;
  const outline = React.useMemo<ReaderReflowOutlineItem[]>(
    () =>
      (completedReflow?.blocks ?? [])
        .filter((block) => block.kind === "heading")
        .map((block) => ({
          id: block.id,
          label: reflowMarkdownPlainText(block.render_markdown),
        }))
        .filter((item) => item.label.length > 0),
    [completedReflow?.blocks],
  );
  const translationStatus = React.useMemo<FullTranslationStatus>(() => {
    if (!fullTranslationEnabled || !completedReflow) return "idle";
    const ids = completedReflow.blocks
      .filter((block) => isTranslatableReflowBlock(block, translateReferences))
      .map((block) => block.id);
    if (ids.some((id) => translations.translations[id]?.status === "error")) {
      return "partial";
    }
    if (
      ids.length > 0 &&
      ids.every((id) => translations.translations[id]?.status === "completed")
    ) {
      return "complete";
    }
    return "translating";
  }, [
    completedReflow,
    fullTranslationEnabled,
    translateReferences,
    translations.translations,
  ]);

  React.useEffect(() => onOutlineChange?.(outline), [onOutlineChange, outline]);
  React.useEffect(
    () => onTranslationStatusChange?.(translationStatus),
    [onTranslationStatusChange, translationStatus],
  );

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
      assets={reflowQuery.data.assets}
      blocks={reflowQuery.data.blocks}
      documentId={documentId}
      fullTranslationDisplay={
        preferences?.full_translation_display ?? "bilingual"
      }
      fullTranslationEnabled={fullTranslationEnabled}
      labels={{
        degradedDescription: t("degradedDescription"),
        degradedTitle: t("degradedTitle"),
        document: t("document"),
        figurePlaceholder: t("figurePlaceholder"),
        openPdfPage: (page) => t("openPdfPage", { page }),
        original: t("original"),
        paperInformation: t("paperInformation"),
        repaired: t("repaired"),
        retryTranslation: t("retryTranslation"),
        translated: t("translated"),
        translationFailed: t("translationFailed"),
        translationMarker: t("translationMarker"),
      }}
      onOpenPdfPage={onOpenPdfPage}
      onRequestTranslation={translations.request}
      onRetryTranslation={translations.retry}
      showTranslationMarker={preferences?.show_translation_marker ?? true}
      targetLanguage={targetLanguage}
      translateReferences={translateReferences}
      translations={translations.translations}
    />
  );
}
