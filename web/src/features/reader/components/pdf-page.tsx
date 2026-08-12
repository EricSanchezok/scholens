"use client";

import type { PDFPageProxy } from "pdfjs-dist";
import * as React from "react";

import { LoadingState, useCopyActionFeedback } from "@/components/feedback";
import { Button } from "@/components/ui";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { PdfDocumentAdapter, renderPdfPage } from "../pdf-document-adapter";

export type ReaderFitMode = "width" | "page" | "custom";
export type ReaderSelection =
  components["schemas"]["PaperSelectionTurnContext"];
type ReaderAnnotation = components["schemas"]["ResearchItemResponse"];

const highlightTone: Record<string, string> = {
  blue: "bg-state-info-bg",
  green: "bg-state-success-bg",
  yellow: "bg-state-warning-bg",
  neutral: "bg-accent",
};

type SelectionRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

export function normalizeReaderSelectionRects(
  pageRect: SelectionRect,
  clientRects: SelectionRect[],
) {
  if (pageRect.width <= 0 || pageRect.height <= 0) return [];
  return clientRects
    .filter((rect) => rect.width > 0 && rect.height > 0)
    .map((rect) => ({
      x: Math.max(0, Math.min(1, (rect.left - pageRect.left) / pageRect.width)),
      y: Math.max(0, Math.min(1, (rect.top - pageRect.top) / pageRect.height)),
      width: Math.max(0, Math.min(1, rect.width / pageRect.width)),
      height: Math.max(0, Math.min(1, rect.height / pageRect.height)),
    }));
}

export function PdfPage({
  adapter,
  annotationLinkLabel,
  fitMode,
  canvasLabel,
  onInternalDestination,
  pageNumber,
  searchQuery,
  zoom,
  loadingLabel,
  annotations = [],
  selectedAnnotationId,
  selection,
  selectionLabels,
  onAnnotationSelect,
  onAskSelection,
  onCommentSelection,
  onHighlightSelection,
  onSelectionChange,
}: {
  adapter: PdfDocumentAdapter;
  annotationLinkLabel: string;
  canvasLabel: string;
  fitMode: ReaderFitMode;
  onInternalDestination: (destination: unknown) => void;
  pageNumber: number;
  searchQuery: string;
  zoom: number;
  loadingLabel: string;
  annotations?: ReaderAnnotation[];
  selectedAnnotationId?: string;
  selection?: ReaderSelection;
  selectionLabels?: {
    ask: string;
    comment: string;
    copy: string;
    copied: string;
    copying: string;
    copyFailed: string;
    highlight: string;
  };
  onAnnotationSelect?: (annotationId: string) => void;
  onAskSelection?: () => void;
  onCommentSelection?: () => void;
  onHighlightSelection?: () => void;
  onSelectionChange?: (selection: ReaderSelection | undefined) => void;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const pageSurfaceRef = React.useRef<HTMLDivElement>(null);
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
  const copyFeedback = useCopyActionFeedback({
    labels: {
      idle: selectionLabels?.copy ?? "",
      pending: selectionLabels?.copying ?? "",
      success: selectionLabels?.copied ?? "",
      error: selectionLabels?.copyFailed ?? "",
    },
    value: selection?.selected_text ?? "",
  });

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
      annotationLinkLabel,
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
  }, [
    annotationLinkLabel,
    onInternalDestination,
    page,
    pageNumber,
    scale,
    searchQuery,
  ]);

  const rendering =
    !page || renderedKey !== `${pageNumber}:${scale}:${searchQuery}`;

  function captureSelection() {
    if (!onSelectionChange) return;
    window.setTimeout(() => {
      const browserSelection = window.getSelection();
      const pageSurface = pageSurfaceRef.current;
      const textLayer = textLayerRef.current;
      if (
        !browserSelection ||
        browserSelection.isCollapsed ||
        browserSelection.rangeCount === 0 ||
        !pageSurface ||
        !textLayer
      ) {
        return;
      }
      const range = browserSelection.getRangeAt(0);
      const ancestor =
        range.commonAncestorContainer.nodeType === Node.TEXT_NODE
          ? range.commonAncestorContainer.parentElement
          : (range.commonAncestorContainer as Element);
      if (!ancestor || !textLayer.contains(ancestor)) return;
      const pageRect = pageSurface.getBoundingClientRect();
      const rects = normalizeReaderSelectionRects(pageRect, [
        ...range.getClientRects(),
      ]);
      const selectedText = browserSelection.toString().trim();
      if (!selectedText || rects.length === 0) return;
      onSelectionChange({
        kind: "paper_selection",
        document_id: "",
        page_number: pageNumber,
        selected_text: selectedText,
        anchor: { kind: "pdf_text", page_number: pageNumber, rects },
      });
    });
  }

  const pageAnnotations = annotations.filter((annotation) => {
    const position = annotation.highlight_thread?.position;
    return position?.kind === "pdf_text" && position.page_number === pageNumber;
  });

  return (
    <div
      aria-label={canvasLabel}
      className="bg-subtle relative grid min-h-0 flex-1 overflow-auto overscroll-contain p-4"
      onPointerUp={captureSelection}
      ref={containerRef}
      role="region"
      tabIndex={0}
    >
      {rendering && (
        <div className="absolute inset-x-0 top-4 z-20 mx-auto w-fit">
          <LoadingState label={loadingLabel} />
        </div>
      )}
      <div
        className="shadow-raised bg-surface relative m-auto shrink-0 overflow-hidden"
        ref={pageSurfaceRef}
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
        <div className="pointer-events-none absolute inset-0 z-10">
          {pageAnnotations.flatMap((annotation) => {
            const thread = annotation.highlight_thread;
            const position = thread?.position;
            if (!thread || position?.kind !== "pdf_text") return [];
            return position.rects.map((rect, index) => (
              <button
                aria-label={thread.quote_text}
                className={cn(
                  "pointer-events-auto absolute rounded-[2px] opacity-45 outline-offset-2 transition-opacity hover:opacity-65",
                  highlightTone[thread.color] ?? highlightTone.blue,
                  selectedAnnotationId === annotation.id &&
                    "opacity-65 ring-2 ring-[var(--color-border-focus)]",
                )}
                key={`${annotation.id}:${index}`}
                onClick={() => onAnnotationSelect?.(annotation.id)}
                style={{
                  height: `${rect.height * 100}%`,
                  left: `${rect.x * 100}%`,
                  top: `${rect.y * 100}%`,
                  width: `${rect.width * 100}%`,
                }}
                type="button"
              />
            ));
          })}
        </div>
        {selection &&
          selection.page_number === pageNumber &&
          selectionLabels && (
            <div
              className="bg-elevated shadow-raised border-line absolute top-3 left-1/2 z-30 flex max-w-[calc(100%-1rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-0.5 rounded-[var(--radius-lg)] border p-1 lg:flex-nowrap lg:rounded-full"
              onPointerDown={(event) => event.stopPropagation()}
            >
              <Button
                className="h-8 min-h-8 rounded-full px-3"
                onClick={onAskSelection}
                size="sm"
                variant="ghost"
              >
                {selectionLabels.ask}
              </Button>
              <Button
                className="h-8 min-h-8 rounded-full px-3"
                onClick={onHighlightSelection}
                size="sm"
                variant="ghost"
              >
                {selectionLabels.highlight}
              </Button>
              <Button
                className="h-8 min-h-8 rounded-full px-3"
                onClick={onCommentSelection}
                size="sm"
                variant="ghost"
              >
                {selectionLabels.comment}
              </Button>
              <Button
                aria-busy={copyFeedback.status === "pending" || undefined}
                className="h-8 min-h-8 rounded-full px-3"
                disabled={copyFeedback.status === "pending"}
                onClick={() => {
                  void copyFeedback.copy().catch(() => undefined);
                }}
                size="sm"
                variant="ghost"
              >
                {copyFeedback.label}
              </Button>
              <span aria-live="polite" className="sr-only">
                {copyFeedback.feedbackVisible ? copyFeedback.label : ""}
              </span>
            </div>
          )}
      </div>
    </div>
  );
}
