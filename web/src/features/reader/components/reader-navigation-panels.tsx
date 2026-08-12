"use client";

import { ArrowLeft } from "iconoir-react";

import {
  IconButton,
  SearchField,
  SheetDescription,
  SheetTitle,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { PdfOutlineEntry } from "../pdf-document-adapter";

export function ReaderOutline({
  entries,
  onSelect,
}: {
  entries: PdfOutlineEntry[];
  onSelect: (destination: unknown) => void;
}) {
  return (
    <ul className="grid gap-0.5">
      {entries.map((entry, index) => (
        <li key={`${entry.title}:${index}`}>
          <button
            className="hover:bg-hover w-full rounded-[var(--radius-md)] px-2 py-2 text-left text-sm"
            onClick={() => onSelect(entry.destination)}
            type="button"
          >
            {entry.title}
          </button>
          {entry.children.length > 0 && (
            <div className="border-line ml-3 border-l pl-2">
              <ReaderOutline entries={entry.children} onSelect={onSelect} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ReaderSearchPanel({
  currentIndex,
  labels,
  matchCount,
  onMove,
  onQueryChange,
  query,
}: {
  currentIndex: number;
  labels: {
    empty: string;
    next: string;
    previous: string;
    results: string;
    title: string;
  };
  matchCount: number;
  onMove: (direction: -1 | 1) => void;
  onQueryChange: (query: string) => void;
  query: string;
}) {
  return (
    <div className="flex h-full flex-col px-5 pt-[max(1.25rem,env(safe-area-inset-top))] pb-[max(1.25rem,env(safe-area-inset-bottom))]">
      <SheetTitle className="pr-12 text-lg font-semibold">
        {labels.title}
      </SheetTitle>
      <SheetDescription className="sr-only">{labels.title}</SheetDescription>
      <SearchField
        autoFocus
        className="mt-5"
        onChange={(event) => onQueryChange(event.currentTarget.value)}
        placeholder={labels.title}
        value={query}
      />
      <div className="mt-3 flex items-center justify-between gap-3">
        <p aria-live="polite" className="text-muted text-sm">
          {query.trim() && matchCount === 0 ? labels.empty : labels.results}
        </p>
        <div className="flex gap-1">
          <IconButton
            disabled={matchCount === 0}
            label={labels.previous}
            onClick={() => onMove(-1)}
            variant="ghost"
          >
            <Icon glyph={ArrowLeft} size={20} />
          </IconButton>
          <IconButton
            disabled={matchCount === 0}
            label={labels.next}
            onClick={() => onMove(1)}
            variant="ghost"
          >
            <Icon className="rotate-180" glyph={ArrowLeft} size={20} />
          </IconButton>
        </div>
      </div>
      {matchCount > 0 && (
        <p className="text-secondary mt-8 text-center text-sm tabular-nums">
          {currentIndex + 1} / {matchCount}
        </p>
      )}
    </div>
  );
}
