"use client";

import type { ReactNode } from "react";

export function ReaderDocumentNavigation({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <aside
      aria-label={label}
      className="border-line bg-canvas flex w-28 shrink-0 flex-col border-r"
    >
      <div className="min-h-0 flex-1 overflow-y-auto p-2">{children}</div>
    </aside>
  );
}
