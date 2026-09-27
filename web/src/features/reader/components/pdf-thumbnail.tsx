"use client";

import * as React from "react";
import type { RenderTask } from "pdfjs-dist";
import { retainPdfPage } from "../pdf-page-resources";

import { focusSurfaceVariants } from "@/components/ui";
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
  const [nearViewport, setNearViewport] = React.useState(current);
  const generation = React.useRef({ value: 0 });
  const renderingRef = React.useRef<Promise<void>>(undefined);
  const visible = nearViewport || current;

  React.useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        setNearViewport(Boolean(entry?.isIntersecting));
      },
      { rootMargin: "160px" },
    );
    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!visible || !canvas) return;
    let active = true;
    const lifecycle = generation.current;
    const currentGeneration = ++lifecycle.value;
    const previousRendering = renderingRef.current;
    let releasePage: (() => void) | undefined;
    let renderTask: RenderTask | undefined;
    const rendering = adapter
      .getPage(pageNumber)
      .then(async (page) => {
        await previousRendering;
        if (!active) return;
        releasePage = retainPdfPage(page);
        const base = page.getViewport({ scale: 1 });
        const scale = 72 / base.width;
        const viewport = page.getViewport({ scale });
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) return;
        renderTask = page.render({ canvas, canvasContext: context, viewport });
        await renderTask.promise;
      })
      // Thumbnail rendering is opportunistic. Cancellation is the expected
      // terminal state when the rail unmounts or the active document changes;
      // a failed thumbnail must never surface as an unhandled page error.
      .catch(() => undefined);
    renderingRef.current = rendering;
    return () => {
      active = false;
      renderTask?.cancel();
      void rendering.finally(() => {
        releasePage?.();
        if (lifecycle.value !== currentGeneration) return;
        canvas.width = 0;
        canvas.height = 0;
      });
    };
  }, [adapter, pageNumber, visible]);

  return (
    <button
      aria-current={current ? "page" : undefined}
      aria-label={label}
      className={cn(
        "hover:bg-hover grid w-full justify-items-center gap-1.5 rounded-[var(--radius-md)] p-2",
        focusSurfaceVariants({ intent: "selection" }),
        current && "bg-pressed",
      )}
      onClick={onSelect}
      ref={rootRef}
      type="button"
    >
      <span className="border-line bg-surface grid min-h-24 w-[74px] place-items-center overflow-hidden rounded-[var(--radius-sm)] border">
        <canvas
          className="max-h-24 max-w-full"
          height={0}
          ref={canvasRef}
          width={0}
        />
      </span>
      <span className="text-muted text-xs tabular-nums">{pageNumber}</span>
    </button>
  );
}
