"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type { PdfOutlineEntry } from "../pdf-document-adapter";
import type { ReaderNavigationMode } from "../reader-types";

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

export function ReaderDocumentNavigation({
  children,
  labels,
  mode,
  onModeChange,
  onOutlineSelect,
  outline,
}: {
  children: ReactNode;
  labels: {
    emptyOutline: string;
    navigation: string;
    outline: string;
    pages: string;
  };
  mode: ReaderNavigationMode;
  onModeChange: (mode: ReaderNavigationMode) => void;
  onOutlineSelect: (destination: unknown) => void;
  outline: PdfOutlineEntry[];
}) {
  return (
    <aside
      aria-label={labels.navigation}
      className={cn(
        "border-line bg-canvas flex shrink-0 flex-col border-r transition-[width] duration-[140ms] motion-reduce:transition-none",
        mode === "outline" ? "w-64" : "w-28",
      )}
    >
      <div className="border-line grid h-11 shrink-0 grid-cols-2 gap-1 border-b p-1">
        <Button
          className="h-9 min-h-9 px-2 text-xs"
          onClick={() => onModeChange("thumbnails")}
          size="sm"
          variant={mode === "thumbnails" ? "secondary" : "ghost"}
        >
          {labels.pages}
        </Button>
        <Button
          className="h-9 min-h-9 px-2 text-xs"
          onClick={() => onModeChange("outline")}
          size="sm"
          variant={mode === "outline" ? "secondary" : "ghost"}
        >
          {labels.outline}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {mode === "thumbnails" ? (
          children
        ) : outline.length > 0 ? (
          <ReaderOutline entries={outline} onSelect={onOutlineSelect} />
        ) : (
          <p className="text-muted px-2 py-12 text-center text-sm">
            {labels.emptyOutline}
          </p>
        )}
      </div>
    </aside>
  );
}
