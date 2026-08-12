"use client";

import * as React from "react";

import { keyboardFocusRing } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type { PdfDocumentAdapter } from "../pdf-document-adapter";

export function PdfThumbnail({
  adapter,
  current,
  label,
  onSelect,
  pageNumber,
}: {
  adapter: PdfDocumentAdapter;
  current: boolean;
  label: string;
  onSelect: () => void;
  pageNumber: number;
}) {
  const rootRef = React.useRef<HTMLButtonElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = React.useState(current);

  React.useEffect(() => {
    const root = rootRef.current;
    if (!root || visible) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "160px" },
    );
    observer.observe(root);
    return () => observer.disconnect();
  }, [visible]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!visible || !canvas) return;
    let active = true;
    void adapter.getPage(pageNumber).then(async (page) => {
      if (!active) return;
      const base = page.getViewport({ scale: 1 });
      const scale = 72 / base.width;
      const viewport = page.getViewport({ scale });
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) return;
      await page.render({ canvas, canvasContext: context, viewport }).promise;
    });
    return () => {
      active = false;
    };
  }, [adapter, pageNumber, visible]);

  return (
    <button
      aria-current={current ? "page" : undefined}
      aria-label={label}
      className={cn(
        "hover:bg-hover grid w-full justify-items-center gap-1.5 rounded-[var(--radius-md)] p-2",
        keyboardFocusRing,
        current && "bg-pressed",
      )}
      onClick={onSelect}
      ref={rootRef}
      type="button"
    >
      <span className="border-line bg-surface grid min-h-24 w-[74px] place-items-center overflow-hidden rounded-[var(--radius-sm)] border">
        <canvas className="max-h-24 max-w-full" ref={canvasRef} />
      </span>
      <span className="text-muted text-xs tabular-nums">{pageNumber}</span>
    </button>
  );
}
