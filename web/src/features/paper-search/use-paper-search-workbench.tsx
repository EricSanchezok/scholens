"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button } from "@/components/ui";
import {
  updatePaperStatus,
  type PaperCollectionWorkbenchProps,
} from "@/features/paper-collection";
import type { PaperSearchResult } from "./api";
import { toPaperSearchCollectionItem } from "./paper-search-display";

export type PaperSearchWorkbenchProps = Pick<
  PaperCollectionWorkbenchProps,
  | "contentState"
  | "items"
  | "onStatusChange"
  | "onTagClick"
  | "personalLabels"
  | "tableFooter"
>;

export function usePaperSearchWorkbench({
  enabled,
  error,
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  onRetry,
  onTagClick,
  papers,
  readerProjectId,
}: {
  enabled: boolean;
  error?: unknown;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  onLoadMore: () => Promise<void>;
  onRetry: () => void;
  onTagClick?: (tagId: string) => void;
  papers: PaperSearchResult[];
  readerProjectId?: string;
}): PaperSearchWorkbenchProps | null {
  const t = useTranslations("PaperSearch.results");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const loadMoreRef = React.useRef<HTMLDivElement>(null);
  const statusMutation = useMutation({
    mutationFn: ({
      documentId,
      status,
    }: {
      documentId: string;
      status: "todo" | "reading" | "completed";
    }) => updatePaperStatus(documentId, status),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library"] }),
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
        queryClient.invalidateQueries({ queryKey: ["paper-search"] }),
      ]);
    },
  });
  const items = React.useMemo(
    () =>
      papers.map((paper) =>
        toPaperSearchCollectionItem(paper, {
          formatDate: (date) =>
            format.dateTime(date, {
              dateStyle: "medium",
            }),
          readerProjectId,
          untitled: t("untitled"),
        }),
      ),
    [format, papers, readerProjectId, t],
  );
  const handleStatusChange = React.useCallback<
    NonNullable<PaperCollectionWorkbenchProps["onStatusChange"]>
  >(
    (item, status) => {
      if (item.inLibrary) {
        statusMutation.mutate({ documentId: item.id, status });
      }
    },
    [statusMutation],
  );
  const handleTagClick = React.useCallback<
    NonNullable<PaperCollectionWorkbenchProps["onTagClick"]>
  >((tag) => onTagClick?.(tag.id), [onTagClick]);
  const resultReady = enabled && !loading && !error && papers.length > 0;

  React.useEffect(() => {
    const target = loadMoreRef.current;
    if (!resultReady || !target || !hasMore || loadingMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void onLoadMore();
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, onLoadMore, resultReady]);

  if (!enabled) return null;

  let contentState: React.ReactNode = undefined;
  if (loading) {
    contentState = (
      <div className="p-4">
        <LoadingState label={t("loading")} />
      </div>
    );
  } else if (error) {
    contentState = (
      <div className="p-4">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: onRetry }}
          description={t("errorDescription")}
          state="error"
          title={t("errorTitle")}
        />
      </div>
    );
  } else if (papers.length === 0) {
    contentState = (
      <div className="p-4">
        <AsyncFeedback
          description={t("emptyDescription")}
          state="empty"
          title={t("emptyTitle")}
        />
      </div>
    );
  }

  return {
    contentState,
    items: contentState === undefined ? items : [],
    onStatusChange: handleStatusChange,
    onTagClick: onTagClick ? handleTagClick : undefined,
    personalLabels: true,
    tableFooter:
      contentState === undefined && hasMore ? (
        <div className="flex justify-center py-6" ref={loadMoreRef}>
          <Button
            loading={loadingMore}
            onClick={() => void onLoadMore()}
            size="sm"
            variant="ghost"
          >
            {loadingMore ? t("loadingMore") : t("loadMore")}
          </Button>
        </div>
      ) : undefined,
  };
}
