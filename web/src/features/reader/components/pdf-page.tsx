"use client";

import type { PDFPageProxy } from "pdfjs-dist";
import * as React from "react";

import { LoadingState } from "@/components/feedback";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { PdfDocumentAdapter, renderPdfPage } from "../pdf-document-adapter";
import {
  ReaderSelectionToolbar,
  type ReaderSelectionLabels,
} from "./reader-selection-toolbar";

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
  activeTextSelection,
  selectionLabels,
  onAnnotationSelect,
  onAskSelection,
  onCommentSelection,
  onHighlightSelection,
  onActiveTextSelectionChange,
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
  activeTextSelection?: ReaderSelection;
  selectionLabels?: ReaderSelectionLabels;
  onAnnotationSelect?: (annotationId: string) => void;
  onAskSelection?: (selection: ReaderSelection) => void;
  onCommentSelection?: (selection: ReaderSelection) => void;
  onHighlightSelection?: (selection: ReaderSelection, color: string) => void;
  onActiveTextSelectionChange?: (
    selection: ReaderSelection | undefined,
  ) => void;
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
  const clearActiveSelection = React.useCallback(() => {
    onActiveTextSelectionChange?.(undefined);
    window.getSelection()?.removeAllRanges();
  }, [onActiveTextSelectionChange]);

  React.useEffect(() => {
    clearActiveSelection();
  }, [clearActiveSelection, pageNumber]);

  React.useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") clearActiveSelection();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [clearActiveSelection]);

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
    const renderTask = renderPdfPage({
      annotationLinkLabel,
      annotationLayer,
      canvas,
      onInternalDestination,
      page,
      scale,
      searchQuery,
      textLayer,
    });
    void renderTask.promise
      .then(() => {
        if (active) setRenderedKey(`${pageNumber}:${scale}:${searchQuery}`);
      })
      .catch((error: unknown) => {
        if (
          error instanceof Error &&
          (error.name === "AbortError" ||
            error.name === "RenderingCancelledException")
        ) {
          return;
        }
      });
    return () => {
      active = false;
      renderTask.cancel();
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
    if (!onActiveTextSelectionChange) return;
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
      onActiveTextSelectionChange({
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
      onPointerDown={(event) => {
        const target = event.target as HTMLElement;
        if (!target.closest("[data-reader-selection-toolbar]")) {
          clearActiveSelection();
        }
      }}
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
        {activeTextSelection &&
          activeTextSelection.page_number === pageNumber &&
          selectionLabels && (
            <div data-reader-selection-toolbar>
              <ReaderSelectionToolbar
                labels={selectionLabels}
                onAsk={() => onAskSelection?.(activeTextSelection)}
                onComment={() => onCommentSelection?.(activeTextSelection)}
                onCopySettled={clearActiveSelection}
                onHighlight={(color) =>
                  onHighlightSelection?.(activeTextSelection, color)
                }
                selection={activeTextSelection}
              />
            </div>
          )}
      </div>
    </div>
  );
}
