"use client";

import * as React from "react";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";

export type ReaderReflowOutlineItem = {
  id: string;
  label: string;
  level: number;
};

export type ReaderReflowOutlineNode = ReaderReflowOutlineItem & {
  children: ReaderReflowOutlineNode[];
};

export function buildReaderReflowOutlineTree(
  entries: ReaderReflowOutlineItem[],
): ReaderReflowOutlineNode[] {
  const roots: ReaderReflowOutlineNode[] = [];
  const stack: ReaderReflowOutlineNode[] = [];

  for (const entry of entries) {
    const node: ReaderReflowOutlineNode = { ...entry, children: [] };
    while (
      stack.length > 0 &&
      entry.level <= (stack.at(-1)?.level ?? entry.level)
    ) {
      stack.pop();
    }
    const parent = stack.at(-1);
    if (parent) parent.children.push(node);
    else roots.push(node);
    stack.push(node);
  }

  return roots;
}

function ReaderReflowOutlineItems({
  depth,
  entries,
  onSelect,
}: {
  depth: number;
  entries: ReaderReflowOutlineNode[];
  onSelect: (id: string) => void;
}) {
  return (
    <ol
      className={cn(
        "grid gap-0.5",
        depth > 0 && "border-line ml-3 border-l pl-2",
      )}
    >
      {entries.map((entry) => (
        <li key={entry.id}>
          <Button
            className={cn(
              "h-auto min-h-11 w-full items-start justify-start px-2 py-2 text-left font-normal whitespace-normal sm:h-auto md:min-h-9 md:py-1.5",
              depth === 0 ? "text-foreground font-medium" : "text-secondary",
            )}
            onClick={() => onSelect(entry.id)}
            size="sm"
            variant="ghost"
          >
            <span className="min-w-0 flex-1 leading-5 [overflow-wrap:anywhere]">
              {entry.label}
            </span>
          </Button>
          {entry.children.length > 0 ? (
            <ReaderReflowOutlineItems
              depth={depth + 1}
              entries={entry.children}
              onSelect={onSelect}
            />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function ReaderReflowOutline({
  className,
  entries,
  label,
  onSelect,
}: {
  className?: string;
  entries: ReaderReflowOutlineItem[];
  label: string;
  onSelect: (id: string) => void;
}) {
  const tree = React.useMemo(
    () => buildReaderReflowOutlineTree(entries),
    [entries],
  );

  return (
    <nav aria-label={label} className={cn("min-w-0 p-2", className)}>
      <ReaderReflowOutlineItems depth={0} entries={tree} onSelect={onSelect} />
    </nav>
  );
}
