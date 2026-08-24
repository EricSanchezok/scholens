"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  focusSurfaceVariants,
  SearchField,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  CommentIcon,
  DocumentIcon,
  ProjectIcon,
} from "@/design-system/icons/semantic-icons";
import { conversationQueries } from "@/features/conversation";
import { useRelativeTimeNow } from "@/i18n/use-relative-time-now";
import type { components } from "@/lib/api/generated/schema";
import { isSearchQuery, normalizeSearchQuery } from "@/lib/search/query";
import { cn } from "@/lib/utilities/cn";
import { paperSearchQueries } from "./api";

type Conversation = components["schemas"]["ConversationSummaryResponse"];
type SearchKind = "conversations" | "papers";

function useDebouncedValue(value: string) {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), 250);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

function ResultList({
  children,
  inputArrowDownRef,
}: {
  children: React.ReactNode;
  inputArrowDownRef: React.MutableRefObject<(() => void) | undefined>;
}) {
  const listRef = React.useRef<HTMLUListElement>(null);

  React.useEffect(() => {
    inputArrowDownRef.current = () => {
      listRef.current
        ?.querySelector<HTMLElement>("[data-search-result]")
        ?.focus();
    };
    return () => {
      inputArrowDownRef.current = undefined;
    };
  }, [inputArrowDownRef]);

  return (
    <ul
      className="divide-line border-line divide-y border-y"
      onKeyDown={(event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        const results = Array.from(
          listRef.current?.querySelectorAll<HTMLElement>(
            "[data-search-result]",
          ) ?? [],
        );
        const current = results.indexOf(event.target as HTMLElement);
        if (current < 0) return;
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        results[(current + delta + results.length) % results.length]?.focus();
      }}
      ref={listRef}
    >
      {children}
    </ul>
  );
}

function LoadMore({
  fetching,
  label,
  loadingLabel,
  onClick,
}: {
  fetching: boolean;
  label: string;
  loadingLabel: string;
  onClick: () => void;
}) {
  return (
    <div className="flex justify-center py-5">
      <Button
        disabled={fetching}
        onClick={onClick}
        size="sm"
        variant="secondary"
      >
        {fetching ? loadingLabel : label}
      </Button>
    </div>
  );
}

export function GlobalSearch({
  conversations,
  onOpenChange,
  open,
}: {
  conversations: Conversation[];
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const t = useTranslations("GlobalSearch");
  const formatRelativeTime = useRelativeTimeNow();
  const [kind, setKind] = React.useState<SearchKind>("conversations");
  const [query, setQuery] = React.useState("");
  const [committedQuery, setCommittedQuery] = React.useState("");
  const composingRef = React.useRef(false);
  const debouncedQuery = useDebouncedValue(committedQuery);
  const resultFocusRef = React.useRef<(() => void) | undefined>(undefined);
  const normalizedQuery = normalizeSearchQuery(debouncedQuery);
  const validQuery = isSearchQuery(normalizedQuery) ? normalizedQuery : "";
  const conversationSearch = useInfiniteQuery(
    conversationQueries.infiniteSearch(
      kind === "conversations" ? validQuery : "",
    ),
  );
  const paperSearch = useInfiniteQuery(
    paperSearchQueries.infiniteResults(kind === "papers" ? validQuery : "", {
      kind: "library",
    }),
  );
  const conversationResults =
    conversationSearch.data?.pages.flatMap((page) => page.items) ?? [];
  const paperResults =
    paperSearch.data?.pages.flatMap((page) => page.items) ?? [];
  const recentConversations = React.useMemo(
    () =>
      [...conversations]
        .sort((left, right) => {
          if (Boolean(left.pinned_at) !== Boolean(right.pinned_at)) {
            return left.pinned_at ? -1 : 1;
          }
          return Date.parse(right.updated_at) - Date.parse(left.updated_at);
        })
        .slice(0, 15),
    [conversations],
  );
  const hasQuery = isSearchQuery(committedQuery);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setKind("conversations");
      setQuery("");
      setCommittedQuery("");
    }
    onOpenChange(nextOpen);
  };

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent
        closeLabel={t("close")}
        className="lg:h-[min(88dvh,46rem)] lg:w-[min(92vw,68rem)] lg:rounded-[var(--radius-2xl)]"
        placement="responsive-full"
      >
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>
        <DialogDescription className="sr-only">
          {t("description")}
        </DialogDescription>
        <Tabs
          className="flex min-h-0 flex-1 flex-col px-4 pt-5 sm:px-7 lg:px-10 lg:pt-8"
          onValueChange={(value) => setKind(value as SearchKind)}
          value={kind}
        >
          <div className="border-line shrink-0 border-b pb-5">
            <h1 className="text-xl font-semibold tracking-[-0.015em] lg:text-2xl">
              {t("title")}
            </h1>
            <p className="text-secondary mt-1 text-sm leading-6">
              {t("description")}
            </p>
            <div className="mt-5 flex min-w-0 items-center gap-2 max-[359px]:flex-col max-[359px]:items-stretch sm:gap-3">
              <TabsList
                aria-label={t("scopeLabel")}
                className="h-12 shrink-0 items-center max-[359px]:w-fit"
              >
                <TabsTrigger value="conversations">
                  {t("tabs.conversations")}
                </TabsTrigger>
                <TabsTrigger value="papers">{t("tabs.papers")}</TabsTrigger>
              </TabsList>
              <div className="min-w-0 flex-1 max-[359px]:w-full">
                <SearchField
                  aria-label={t("inputLabel")}
                  autoFocus
                  className="h-12 rounded-[var(--radius-lg)] text-base"
                  onChange={(event) => {
                    const nextQuery = event.currentTarget.value;
                    setQuery(nextQuery);
                    if (!composingRef.current) setCommittedQuery(nextQuery);
                  }}
                  onCompositionEnd={(event) => {
                    composingRef.current = false;
                    setQuery(event.currentTarget.value);
                    setCommittedQuery(event.currentTarget.value);
                  }}
                  onCompositionStart={() => {
                    composingRef.current = true;
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowDown") {
                      event.preventDefault();
                      resultFocusRef.current?.();
                    }
                  }}
                  placeholder={
                    kind === "conversations"
                      ? t("conversationPlaceholder")
                      : t("paperPlaceholder")
                  }
                  value={query}
                />
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1">
            <TabsContent
              className={cn(
                "h-full min-h-0 overflow-y-auto overscroll-contain pt-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]",
                focusSurfaceVariants({ intent: "scroll" }),
              )}
              data-scrollbar-gutter="stable"
              value="conversations"
            >
              {!hasQuery ? (
                <>
                  <h2 className="text-secondary mb-2 px-3 text-xs font-semibold">
                    {t("recentConversations")}
                  </h2>
                  {recentConversations.length ? (
                    <ResultList inputArrowDownRef={resultFocusRef}>
                      {recentConversations.map((conversation) => (
                        <li key={conversation.id}>
                          <Link
                            className={cn(
                              "hover:bg-hover active:bg-pressed motion-control flex min-w-0 items-start gap-3 rounded-[var(--radius-lg)] px-3 py-3",
                              focusSurfaceVariants({ intent: "neutral" }),
                            )}
                            data-search-result=""
                            href={`/?conversation=${conversation.id}` as Route}
                            onClick={() => handleOpenChange(false)}
                          >
                            <Icon
                              className="mt-0.5 shrink-0"
                              glyph={CommentIcon}
                              size={20}
                              tone="secondary"
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-semibold">
                                {conversation.title}
                              </span>
                              <span className="text-secondary mt-1 block truncate text-xs">
                                {formatRelativeTime(conversation.updated_at)}
                                {conversation.scope_label &&
                                  ` · ${conversation.scope_label}`}
                              </span>
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ResultList>
                  ) : (
                    <p className="text-secondary px-3 py-12 text-center text-sm">
                      {t("noRecentConversations")}
                    </p>
                  )}
                </>
              ) : conversationSearch.isPending ? (
                <LoadingState label={t("searchingConversations")} />
              ) : conversationSearch.isError ? (
                <AsyncFeedback
                  action={{
                    label: t("retry"),
                    onClick: () => void conversationSearch.refetch(),
                  }}
                  description={t("errorDescription")}
                  state="error"
                  title={t("errorTitle")}
                />
              ) : conversationResults.length === 0 ? (
                <AsyncFeedback
                  description={t("conversationEmptyDescription")}
                  state="empty"
                  title={t("conversationEmptyTitle")}
                />
              ) : (
                <>
                  <p className="text-secondary mb-2 px-3 text-xs">
                    {t("conversationCount", {
                      count: conversationSearch.data.pages[0]?.total ?? 0,
                    })}
                  </p>
                  <ResultList inputArrowDownRef={resultFocusRef}>
                    {conversationResults.map((result) => (
                      <li key={result.conversation.id}>
                        <Link
                          className={cn(
                            "hover:bg-hover active:bg-pressed motion-control flex min-w-0 items-start gap-3 rounded-[var(--radius-lg)] px-3 py-3",
                            focusSurfaceVariants({ intent: "neutral" }),
                          )}
                          data-search-result=""
                          href={
                            `/?conversation=${result.conversation.id}` as Route
                          }
                          onClick={() => handleOpenChange(false)}
                        >
                          <Icon
                            className="mt-0.5 shrink-0"
                            glyph={
                              result.conversation.scope_type === "project"
                                ? ProjectIcon
                                : CommentIcon
                            }
                            size={20}
                            tone="secondary"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold">
                              {result.conversation.title}
                            </span>
                            <span className="text-secondary mt-1 block truncate text-xs">
                              {t(`matches.${result.matched_field}`)} ·{" "}
                              {formatRelativeTime(
                                result.conversation.updated_at,
                              )}
                              {result.conversation.scope_label &&
                                ` · ${result.conversation.scope_label}`}
                            </span>
                            {result.snippet && (
                              <span className="text-secondary mt-1 line-clamp-2 block text-xs leading-5">
                                {result.snippet}
                              </span>
                            )}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ResultList>
                  {conversationSearch.hasNextPage && (
                    <LoadMore
                      fetching={conversationSearch.isFetchingNextPage}
                      label={t("loadMore")}
                      loadingLabel={t("loadingMore")}
                      onClick={() => void conversationSearch.fetchNextPage()}
                    />
                  )}
                </>
              )}
            </TabsContent>

            <TabsContent
              className={cn(
                "h-full min-h-0 overflow-y-auto overscroll-contain pt-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]",
                focusSurfaceVariants({ intent: "scroll" }),
              )}
              data-scrollbar-gutter="stable"
              value="papers"
            >
              {!hasQuery ? (
                <div className="mx-auto max-w-xl px-4 py-16 text-center">
                  <Icon
                    className="mx-auto"
                    glyph={DocumentIcon}
                    size={24}
                    tone="secondary"
                  />
                  <p className="text-secondary mt-4 text-sm leading-6">
                    {t("paperHint")}
                  </p>
                </div>
              ) : paperSearch.isPending ? (
                <LoadingState label={t("searchingPapers")} />
              ) : paperSearch.isError ? (
                <AsyncFeedback
                  action={{
                    label: t("retry"),
                    onClick: () => void paperSearch.refetch(),
                  }}
                  description={t("errorDescription")}
                  state="error"
                  title={t("errorTitle")}
                />
              ) : paperResults.length === 0 ? (
                <AsyncFeedback
                  description={t("paperEmptyDescription")}
                  state="empty"
                  title={t("paperEmptyTitle")}
                />
              ) : (
                <>
                  <p className="text-secondary mb-2 px-3 text-xs">
                    {t("paperCount", {
                      count: paperSearch.data.pages[0]?.total ?? 0,
                    })}
                  </p>
                  <ResultList inputArrowDownRef={resultFocusRef}>
                    {paperResults.map((paper) => (
                      <li key={paper.document_id}>
                        <Link
                          className={cn(
                            "hover:bg-hover active:bg-pressed motion-control flex min-w-0 items-start gap-3 rounded-[var(--radius-lg)] px-3 py-3",
                            focusSurfaceVariants({ intent: "neutral" }),
                          )}
                          data-search-result=""
                          href={`/reader/${paper.document_id}` as Route}
                          onClick={() => handleOpenChange(false)}
                        >
                          <Icon
                            className="mt-0.5 shrink-0"
                            glyph={DocumentIcon}
                            size={20}
                            tone="secondary"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="line-clamp-2 block text-sm font-semibold [overflow-wrap:anywhere]">
                              {paper.title || t("untitled")}
                            </span>
                            <span className="text-secondary mt-1 block truncate text-xs">
                              {paper.authors?.join(" · ") ||
                                t("unknownAuthors")}
                            </span>
                            {(paper.snippets?.[0]?.text || paper.abstract) && (
                              <span className="text-secondary mt-1 line-clamp-2 block text-xs leading-5">
                                {paper.snippets?.[0]?.text || paper.abstract}
                              </span>
                            )}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ResultList>
                  {paperSearch.hasNextPage && (
                    <LoadMore
                      fetching={paperSearch.isFetchingNextPage}
                      label={t("loadMore")}
                      loadingLabel={t("loadingMore")}
                      onClick={() => void paperSearch.fetchNextPage()}
                    />
                  )}
                </>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
