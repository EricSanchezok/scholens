"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button, LinkButton, useToast } from "@/components/ui";
import { integrationQueries } from "@/features/integrations";
import { useSettingsLauncher } from "@/features/settings";
import { ApiError } from "@/lib/api/errors";
import { academicMarkdownToPlainText } from "@/lib/content/academic-text";
import { reflowKeys, reflowQueries, requestDocumentReflowAttempt } from "./api";
import {
  isTranslatableReflowBlock,
  ReaderReflowView,
} from "./reader-reflow-view";
import type { ReaderReflowOutlineItem } from "./reader-reflow-outline";
import type { DocumentReflowSourceSpan } from "./api";
import { useReflowTranslations } from "./use-reflow-translations";
import type {
  FullTranslationStatus,
  TranslationPreferences,
} from "../translation";

export function ReaderReflowSurface({
  documentId,
  fullTranslationEnabled,
  onOutlineChange,
  onOpenPdfSource,
  onTranslationStatusChange,
  preferences,
  scrollContainerRef,
  targetLanguage,
  translationCacheVersion,
}: {
  documentId: string;
  fullTranslationEnabled: boolean;
  onOutlineChange?: (items: ReaderReflowOutlineItem[]) => void;
  onOpenPdfSource: (source: DocumentReflowSourceSpan) => void;
  onTranslationStatusChange?: (status: FullTranslationStatus) => void;
  preferences?: TranslationPreferences;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  targetLanguage: string;
  translationCacheVersion?: string;
}) {
  const queryClient = useQueryClient();
  const t = useTranslations("Reader.reflow");
  const toast = useToast();
  const { openSection: openSettingsSection } = useSettingsLauncher();
  const [mineruRequired, setMineruRequired] = React.useState(false);
  const [requesting, setRequesting] = React.useState(false);
  const attemptKey = React.useRef<string | undefined>(undefined);
  const resumedConnection = React.useRef<string | undefined>(undefined);
  const reflowQuery = useQuery(reflowQueries.document(documentId, true));
  const integrations = useQuery({
    ...integrationQueries.current(),
    enabled: mineruRequired,
  });
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
          label: academicMarkdownToPlainText(block.render_markdown),
          level: block.heading_level ?? 2,
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

  const requestAttempt = React.useCallback(async () => {
    if (requesting) return;
    setRequesting(true);
    attemptKey.current ??= crypto.randomUUID();
    try {
      const result = await requestDocumentReflowAttempt(
        documentId,
        attemptKey.current,
      );
      queryClient.setQueryData(reflowKeys.document(documentId), result);
      attemptKey.current = undefined;
      setMineruRequired(false);
    } catch (error) {
      if (
        error instanceof ApiError &&
        ["mineru_credential_required", "mineru_credential_invalid"].includes(
          error.code ?? "",
        )
      ) {
        setMineruRequired(true);
        openSettingsSection("connections");
        toast.notify({
          description: t("mineruRequiredDescription"),
          title: t("mineruRequiredTitle"),
        });
        return;
      }
      toast.notify({
        description: t("retryFailedDescription"),
        title: t("retryFailedTitle"),
      });
    } finally {
      setRequesting(false);
    }
  }, [documentId, openSettingsSection, queryClient, requesting, t, toast]);

  const mineru = integrations.data?.items.find(
    (integration) => integration.provider === "mineru",
  );
  React.useEffect(() => {
    const connectionVersion = mineru?.updated_at ?? undefined;
    if (
      mineruRequired &&
      mineru?.enabled &&
      ["connected", "connected_unverified"].includes(mineru.state) &&
      connectionVersion &&
      resumedConnection.current !== connectionVersion
    ) {
      resumedConnection.current = connectionVersion;
      void requestAttempt();
    }
  }, [
    mineru?.enabled,
    mineru?.state,
    mineru?.updated_at,
    mineruRequired,
    requestAttempt,
  ]);

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
  const credentialFailure =
    mineruRequired ||
    reflowQuery.data?.failure?.required_integration === "mineru";
  if (credentialFailure) {
    return (
      <section className="m-auto grid w-full max-w-md justify-items-center gap-4 p-6 text-center">
        <div>
          <h2 className="text-base font-semibold">
            {t("mineruRequiredTitle")}
          </h2>
          <p className="text-secondary mt-2 text-sm leading-6">
            {t("mineruRequiredDescription")}
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            onClick={() => openSettingsSection("connections")}
            variant="primary"
          >
            {t("connectMineru")}
          </Button>
          <LinkButton
            href="https://mineru.net/apiManage/token"
            rel="noreferrer"
            target="_blank"
            variant="secondary"
          >
            {t("getMineruToken")}
          </LinkButton>
        </div>
      </section>
    );
  }
  const failureCode = reflowQuery.data?.failure?.code;
  let failureDescription = t("failedDescription");
  switch (failureCode) {
    case "mineru_rate_limited":
      failureDescription = t("failureMineruRateLimited");
      break;
    case "mineru_unavailable":
      failureDescription = t("failureMineruUnavailable");
      break;
    case "mineru_content_insufficient":
      failureDescription = t("failureMineruContentInsufficient");
      break;
    case "mineru_response_unsafe":
      failureDescription = t("failureMineruResponseUnsafe");
      break;
  }
  if (reflowQuery.isError || reflowQuery.data?.status === "failed") {
    const canRetry =
      reflowQuery.isError || reflowQuery.data?.failure?.retryable !== false;
    return (
      <div className="m-auto w-full max-w-md p-6">
        <AsyncFeedback
          action={
            canRetry
              ? { label: t("retry"), onClick: () => void requestAttempt() }
              : undefined
          }
          description={failureDescription}
          state="error"
          title={t("failedTitle")}
        />
      </div>
    );
  }
  if (reflowQuery.data?.status === "not_requested") {
    return (
      <div className="m-auto w-full max-w-md p-6">
        <AsyncFeedback
          action={{ label: t("start"), onClick: () => void requestAttempt() }}
          description={t("notRequestedDescription")}
          state="empty"
          title={t("notRequestedTitle")}
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
      onOpenPdfSource={onOpenPdfSource}
      onRequestTranslation={translations.request}
      onRetryTranslation={translations.retry}
      scrollContainerRef={scrollContainerRef}
      showTranslationMarker={preferences?.show_translation_marker ?? true}
      targetLanguage={targetLanguage}
      translateReferences={translateReferences}
      translations={translations.translations}
    />
  );
}
