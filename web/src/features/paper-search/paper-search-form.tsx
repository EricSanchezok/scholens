"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { isImeComposing, SearchField } from "@/components/ui";
import { isSearchQuery, normalizeSearchQuery } from "@/lib/search/query";

export function usePaperSearchDraft(
  committedQuery: string,
  synchronizationScope = "paper-search",
) {
  const [state, setState] = React.useState(() => ({
    committedQuery,
    draft: committedQuery,
    synchronizationScope,
  }));
  const setDraft = React.useCallback(
    (draft: string) => {
      setState({ committedQuery, draft, synchronizationScope });
    },
    [committedQuery, synchronizationScope],
  );
  const needsSynchronization =
    state.committedQuery !== committedQuery ||
    state.synchronizationScope !== synchronizationScope;

  if (needsSynchronization) {
    setState({
      committedQuery,
      draft: committedQuery,
      synchronizationScope,
    });
  }

  return [
    needsSynchronization ? committedQuery : state.draft,
    setDraft,
  ] as const;
}

export function PaperSearchForm({
  committedQuery,
  draft,
  label,
  onCommit,
  onDraftChange,
}: {
  committedQuery: string;
  draft: string;
  label: string;
  onCommit: (query: string) => void;
  onDraftChange: (query: string) => void;
}) {
  const t = useTranslations("PaperSearch.form");
  const errorId = React.useId();
  const composingRef = React.useRef(false);
  const [invalidDraft, setInvalidDraft] = React.useState<string>();
  const invalid = invalidDraft === draft;

  const submit = React.useCallback(() => {
    const normalized = normalizeSearchQuery(draft);
    onDraftChange(normalized);

    if (normalized.length > 0 && !isSearchQuery(normalized)) {
      setInvalidDraft(normalized);
      return;
    }

    setInvalidDraft(undefined);
    if (normalized !== committedQuery) onCommit(normalized);
  }, [committedQuery, draft, onCommit, onDraftChange]);

  return (
    <form
      aria-label={label}
      className="min-w-0"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!composingRef.current) submit();
      }}
      role="search"
    >
      <SearchField
        aria-describedby={invalid ? errorId : undefined}
        aria-invalid={invalid || undefined}
        aria-label={label}
        className="border-line text-base sm:text-sm"
        onChange={(event) => {
          const nextDraft = event.currentTarget.value;
          if (invalid) setInvalidDraft(undefined);
          onDraftChange(nextDraft);
          if (
            normalizeSearchQuery(nextDraft).length === 0 &&
            committedQuery.length > 0
          ) {
            onCommit("");
          }
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
        }}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            (composingRef.current || isImeComposing(event))
          ) {
            event.preventDefault();
          }
        }}
        placeholder={label}
        surfaceClassName="rounded-full"
        value={draft}
      />
      {invalid ? (
        <p
          aria-live="polite"
          className="text-danger mt-1 px-3 text-xs leading-5"
          id={errorId}
        >
          {t("minimumQuery")}
        </p>
      ) : null}
    </form>
  );
}
