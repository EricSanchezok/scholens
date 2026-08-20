"use client";

import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button, keyboardFocusRing } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type { PaperSearchResult } from "./api";

function SearchPreview({ paper }: { paper: PaperSearchResult }) {
  const t = useTranslations("PaperSearch.results");
  const excerpt = paper.snippets?.[0]?.text || paper.abstract;
  return (
    <aside
      aria-label={t("preview")}
      className="border-line sticky top-4 hidden max-h-[calc(100dvh-8rem)] min-w-0 overflow-y-auto border-l pl-5 xl:block"
    >
      {paper.preview_url ? (
        // Server returns a short-lived authenticated object-store URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="border-line bg-subtle mx-auto max-h-56 w-auto rounded-[var(--radius-md)] border object-contain"
          src={paper.preview_url}
        />
      ) : null}
      <h2 className="mt-4 text-base leading-6 font-semibold [overflow-wrap:anywhere]">
        {paper.title || t("untitled")}
      </h2>
      <p className="text-secondary mt-2 text-xs leading-5">
        {paper.authors?.join(" · ") || t("unknownAuthors")}
      </p>
      <p className="text-secondary mt-5 text-xs font-medium">
        {t("bestMatch")}
      </p>
      <p className="text-secondary mt-2 text-sm leading-6">
        {excerpt || t("noExcerpt")}
      </p>
      <Button asChild className="mt-5 w-full" size="sm" variant="secondary">
        <Link href={`/reader/${paper.document_id}` as Route}>
          {t("openReader")}
        </Link>
      </Button>
    </aside>
  );
}

export function PaperSearchResults({
  error,
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  onRetry,
  papers,
  total,
}: {
  error?: unknown;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  onLoadMore: () => Promise<void>;
  onRetry: () => void;
  papers: PaperSearchResult[];
  total?: number;
}) {
  const t = useTranslations("PaperSearch.results");
  const [previewId, setPreviewId] = React.useState<string>();
  const loadMoreRef = React.useRef<HTMLDivElement>(null);
  const preview =
    papers.find((paper) => paper.document_id === previewId) ?? papers[0];

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
      <p className="text-secondary mb-3 text-xs">
        {t("count", { count: total ?? papers.length })}
      </p>
      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <ul className="divide-line border-line min-w-0 divide-y border-y">
          {papers.map((paper) => {
            const excerpt = paper.snippets?.[0]?.text || paper.abstract;
            return (
              <li
                className="hover:bg-hover focus-within:bg-hover active:bg-pressed motion-control min-w-0 rounded-[var(--radius-lg)]"
                key={paper.document_id}
                onFocusCapture={() => setPreviewId(paper.document_id)}
                onMouseEnter={() => setPreviewId(paper.document_id)}
              >
                <Link
                  className={cn(
                    "grid min-w-0 gap-1 px-3 py-3",
                    keyboardFocusRing,
                  )}
                  href={`/reader/${paper.document_id}` as Route}
                >
                  <span className="line-clamp-2 text-sm leading-5 font-semibold [overflow-wrap:anywhere] md:line-clamp-1">
                    {paper.title || t("untitled")}
                  </span>
                  <span className="text-secondary truncate text-xs">
                    {paper.authors?.join(" · ") || t("unknownAuthors")}
                  </span>
                  {excerpt ? (
                    <span className="text-secondary mt-1 line-clamp-2 text-xs leading-5">
                      {excerpt}
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
        {preview ? <SearchPreview paper={preview} /> : null}
      </div>
      {hasMore ? (
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
      ) : null}
    </div>
  );
}
