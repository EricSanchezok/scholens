"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  SearchField,
  keyboardFocusRing,
} from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { paperSearchQueries } from "./api";

function useDebouncedValue(value: string) {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), 250);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

export function GlobalPaperSearch({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const t = useTranslations("PaperSearch");
  const [query, setQuery] = React.useState("");
  const debouncedQuery = useDebouncedValue(query);
  const results = useQuery(
    paperSearchQueries.results(debouncedQuery, { kind: "library" }),
  );

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) setQuery("");
    onOpenChange(nextOpen);
  };

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent closeLabel={t("close")} placement="responsive-bottom">
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex min-h-0 flex-col gap-4">
          <SearchField
            aria-label={t("inputLabel")}
            autoFocus
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={t("placeholder")}
            value={query}
          />
          <div
            aria-live="polite"
            className="min-h-48 overflow-y-auto"
            data-scrollbar-gutter="stable"
          >
            {query.trim().length < 2 ? (
              <p className="text-secondary px-2 py-12 text-center text-sm leading-6">
                {t("hint")}
              </p>
            ) : results.isPending ? (
              <LoadingState label={t("searching")} />
            ) : results.isError ? (
              <AsyncFeedback
                action={{
                  label: t("retry"),
                  onClick: () => void results.refetch(),
                }}
                description={t("errorDescription")}
                state="error"
                title={t("errorTitle")}
              />
            ) : results.data.items.length === 0 ? (
              <AsyncFeedback
                description={t("emptyDescription")}
                state="empty"
                title={t("emptyTitle")}
              />
            ) : (
              <ul className="divide-line border-line divide-y border-y">
                {results.data.items.map((paper) => (
                  <li key={paper.document_id}>
                    <Link
                      className={cn(
                        "hover:bg-hover active:bg-pressed motion-control grid min-w-0 gap-1 rounded-[var(--radius-lg)] px-3 py-3",
                        keyboardFocusRing,
                      )}
                      href={`/reader/${paper.document_id}` as Route}
                      onClick={() => handleOpenChange(false)}
                    >
                      <span className="line-clamp-2 text-sm font-semibold [overflow-wrap:anywhere]">
                        {paper.title || t("untitled")}
                      </span>
                      <span className="text-secondary truncate text-xs">
                        {paper.authors?.join(" · ") || t("unknownAuthors")}
                      </span>
                      {(paper.snippets?.[0]?.text || paper.abstract) && (
                        <span className="text-secondary line-clamp-2 text-xs leading-5">
                          {paper.snippets?.[0]?.text || paper.abstract}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
