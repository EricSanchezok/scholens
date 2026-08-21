"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button } from "@/components/ui";
import {
  PaperCollectionWorkbench,
  updatePaperStatus,
  type PaperCollectionItem,
} from "@/features/paper-collection";
import type { PaperSearchResult } from "./api";

export function PaperSearchResults({
  error,
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  onRetry,
  onTagClick,
  papers,
  readerProjectId,
  toolbar,
  total,
}: {
  error?: unknown;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  onLoadMore: () => Promise<void>;
  onRetry: () => void;
  onTagClick?: (tagId: string) => void;
  papers: PaperSearchResult[];
  readerProjectId?: string;
  toolbar?: React.ReactNode;
  total?: number;
}) {
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
  const items = React.useMemo<PaperCollectionItem[]>(
    () =>
      papers.map((paper) => ({
        abstract: paper.abstract ?? undefined,
        addedAt: format.dateTime(new Date(paper.created_at), {
          dateStyle: "medium",
        }),
        authors: paper.authors ?? [],
        doi: paper.doi ?? undefined,
        href: (readerProjectId
          ? `/reader/${paper.document_id}?project=${readerProjectId}`
          : `/reader/${paper.document_id}`) as Route,
        id: paper.document_id,
        inLibrary: Boolean(paper.personal_status),
        keywords: paper.keywords ?? [],
        lastOpened: paper.personal_last_accessed_at
          ? format.dateTime(new Date(paper.personal_last_accessed_at), {
              dateStyle: "medium",
            })
          : undefined,
        previewUrl: paper.preview_url ?? undefined,
        publication: [
          paper.journal,
          paper.publish_date
            ? new Date(paper.publish_date).getUTCFullYear().toString()
            : undefined,
        ]
          .filter(Boolean)
          .join(" · "),
        snippet: paper.snippets?.[0]?.text ?? undefined,
        status: paper.personal_status ?? undefined,
        summary: paper.summary ?? undefined,
        tags: paper.personal_tags ?? [],
        title: paper.title || t("untitled"),
      })),
    [format, papers, readerProjectId, t],
  );

  React.useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || !hasMore || loadingMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void onLoadMore();
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, onLoadMore]);

  if (loading) return <LoadingState label={t("loading")} />;
  if (error) {
    return (
      <AsyncFeedback
        action={{ label: t("retry"), onClick: onRetry }}
        description={t("errorDescription")}
        state="error"
        title={t("errorTitle")}
      />
    );
  }
  if (papers.length === 0) {
    return (
      <AsyncFeedback
        description={t("emptyDescription")}
        state="empty"
        title={t("emptyTitle")}
      />
    );
  }

  return (
    <div className="min-w-0">
      <PaperCollectionWorkbench
        items={items}
        onStatusChange={(item, status) => {
          if (item.inLibrary) {
            statusMutation.mutate({ documentId: item.id, status });
          }
        }}
        onTagClick={(tag) => onTagClick?.(tag.id)}
        personalLabels
        tableFooter={
          hasMore ? (
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
          ) : null
        }
        toolbar={
          <div className="flex min-w-0 items-center gap-3">
            {toolbar ? <div className="min-w-0 flex-1">{toolbar}</div> : null}
            <p className="text-secondary shrink-0 text-xs">
              {t("count", { count: total ?? papers.length })}
            </p>
          </div>
        }
      />
    </div>
  );
}
