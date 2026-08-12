"use client";

import type { PDFPageProxy } from "pdfjs-dist";
import * as React from "react";

import { LoadingState } from "@/components/feedback";
import { PdfDocumentAdapter, renderPdfPage } from "../pdf-document-adapter";

export type ReaderFitMode = "width" | "page" | "custom";

export function PdfPage({
  adapter,
  fitMode,
  onInternalDestination,
  pageNumber,
  searchQuery,
  zoom,
  loadingLabel,
}: {
  adapter: PdfDocumentAdapter;
  fitMode: ReaderFitMode;
  onInternalDestination: (destination: unknown) => void;
  pageNumber: number;
  searchQuery: string;
  zoom: number;
  loadingLabel: string;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const textLayerRef = React.useRef<HTMLDivElement>(null);
  const annotationLayerRef = React.useRef<HTMLDivElement>(null);
  const [pageState, setPageState] = React.useState<{
    page: PDFPageProxy;
    pageNumber: number;
  }>();
  const [containerSize, setContainerSize] = React.useState({
    height: 0,
    width: 0,
  });
  const [pageSize, setPageSize] = React.useState({ height: 1, width: 1 });
  const [renderedKey, setRenderedKey] = React.useState("");

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setContainerSize({
        height: entry.contentRect.height,
        width: entry.contentRect.width,
      });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  React.useEffect(() => {
    let active = true;
    void adapter.getPage(pageNumber).then((nextPage) => {
      if (!active) return;
      const viewport = nextPage.getViewport({ scale: 1 });
      setPageSize({ height: viewport.height, width: viewport.width });
      setPageState({ page: nextPage, pageNumber });
    });
    return () => {
      active = false;
    };
  }, [adapter, pageNumber]);

  const page =
    pageState?.pageNumber === pageNumber ? pageState.page : undefined;

  const scale = React.useMemo(() => {
    if (fitMode === "custom") return zoom;
    const widthScale = Math.max(
      (containerSize.width - 32) / pageSize.width,
      0.1,
    );
    if (fitMode === "width") return widthScale;
    const heightScale = Math.max(
      (containerSize.height - 32) / pageSize.height,
      0.1,
    );
    return Math.min(widthScale, heightScale);
  }, [containerSize, fitMode, pageSize, zoom]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const textLayer = textLayerRef.current;
    const annotationLayer = annotationLayerRef.current;
    if (!page || !canvas || !textLayer || !annotationLayer) return;
    let active = true;
    let cancel: (() => void) | undefined;
    void renderPdfPage({
      annotationLayer,
      canvas,
      onInternalDestination,
      page,
      scale,
      searchQuery,
      textLayer,
    })
      .then((result) => {
        cancel = result.cancel;
        if (active) setRenderedKey(`${pageNumber}:${scale}:${searchQuery}`);
      })
      .catch((error: unknown) => {
        if (
          error instanceof Error &&
          error.name === "RenderingCancelledException"
        ) {
          return;
        }
      });
    return () => {
      active = false;
      cancel?.();
    };
  }, [onInternalDestination, page, pageNumber, scale, searchQuery]);

  const rendering =
    !page || renderedKey !== `${pageNumber}:${scale}:${searchQuery}`;

  return (
    <div
      className="bg-subtle relative grid min-h-0 flex-1 overflow-auto overscroll-contain p-4"
      ref={containerRef}
    >
      {rendering && (
        <div className="absolute inset-x-0 top-4 z-20 mx-auto w-fit">
          <LoadingState label={loadingLabel} />
        </div>
      )}
      <div
        className="shadow-raised bg-surface relative m-auto shrink-0 overflow-hidden"
        style={{
          height: `${pageSize.height * scale}px`,
          width: `${pageSize.width * scale}px`,
        }}
      >
        <canvas className="absolute inset-0" ref={canvasRef} />
        <div
          className="textLayer pdf-text-layer absolute inset-0 overflow-hidden opacity-100"
          ref={textLayerRef}
        />
        <div
          className="pdf-annotation-layer pointer-events-none absolute inset-0 [&_a]:pointer-events-auto [&_a]:outline-offset-2"
          ref={annotationLayerRef}
        />
      </div>
    </div>
  );
}
