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

export function selectReaderViewportPage(
  viewport: { bottom: number; top: number },
  pages: Array<{ bottom: number; pageNumber: number; top: number }>,
) {
  const viewportCenter = (viewport.top + viewport.bottom) / 2;
  let best:
    { distance: number; pageNumber: number; visibleHeight: number } | undefined;

  for (const page of pages) {
    const visibleHeight = Math.max(
      0,
      Math.min(page.bottom, viewport.bottom) - Math.max(page.top, viewport.top),
    );
    if (visibleHeight === 0) continue;
    const distance = Math.abs((page.top + page.bottom) / 2 - viewportCenter);
    if (
      !best ||
      visibleHeight > best.visibleHeight ||
      (visibleHeight === best.visibleHeight && distance < best.distance)
    ) {
      best = { distance, pageNumber: page.pageNumber, visibleHeight };
    }
  }

  return best?.pageNumber;
}

function PdfPageSurface({
  adapter,
  annotationLinkLabel,
  fitMode,
  containerSize,
  currentPageNumber,
  onInternalDestination,
  pageNumber,
  searchQuery,
  scrollContainerRef,
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
  containerSize: { height: number; width: number };
  currentPageNumber: number;
  fitMode: ReaderFitMode;
  onInternalDestination: (destination: unknown) => void;
  pageNumber: number;
  searchQuery: string;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
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
  const pageSurfaceRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const textLayerRef = React.useRef<HTMLDivElement>(null);
  const annotationLayerRef = React.useRef<HTMLDivElement>(null);
  const [pageState, setPageState] = React.useState<{
    page: PDFPageProxy;
    pageNumber: number;
  }>();
  const [pageSize, setPageSize] = React.useState({ height: 792, width: 612 });
  const [renderEnabled, setRenderEnabled] = React.useState(
    pageNumber === currentPageNumber,
  );
  const [renderedKey, setRenderedKey] = React.useState("");

  React.useEffect(() => {
    const surface = pageSurfaceRef.current;
    const root = scrollContainerRef.current;
    if (!surface || !root) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        setRenderEnabled(Boolean(entry?.isIntersecting));
      },
      { root, rootMargin: "100% 0px" },
    );
    observer.observe(surface);
    return () => observer.disconnect();
  }, [pageNumber, scrollContainerRef]);

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
  const shouldRender = renderEnabled || pageNumber === currentPageNumber;

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
    if (!shouldRender || !page || !canvas || !textLayer || !annotationLayer)
      return;
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
    shouldRender,
    scale,
    searchQuery,
  ]);

  const rendering =
    shouldRender &&
    (!page || renderedKey !== `${pageNumber}:${scale}:${searchQuery}`);

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
      window.requestAnimationFrame(() => {
        window.getSelection()?.removeAllRanges();
      });
    });
  }

  const pageAnnotations = annotations.filter((annotation) => {
    const position = annotation.highlight_thread?.position;
    return position?.kind === "pdf_text" && position.page_number === pageNumber;
  });

  return (
    <article
      className="shadow-raised bg-surface relative mx-auto shrink-0 overflow-hidden"
      data-pdf-page-number={pageNumber}
      onPointerUp={captureSelection}
      ref={pageSurfaceRef}
      style={{
        height: `${pageSize.height * scale}px`,
        width: `${pageSize.width * scale}px`,
      }}
    >
      {rendering && (
        <div className="absolute inset-x-0 top-4 z-30 mx-auto w-fit">
          <LoadingState label={loadingLabel} />
        </div>
      )}
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
      {activeTextSelection?.page_number === pageNumber &&
      activeTextSelection.anchor.kind === "pdf_text" ? (
        <div
          className="pointer-events-none absolute inset-0 z-20"
          data-active-selection-overlay
        >
          {activeTextSelection.anchor.rects.map((rect, index) => (
            <span
              className="pdf-selection-overlay absolute rounded-[2px]"
              key={index}
              style={{
                height: `${rect.height * 100}%`,
                left: `${rect.x * 100}%`,
                top: `${rect.y * 100}%`,
                width: `${rect.width * 100}%`,
              }}
            />
          ))}
        </div>
      ) : null}
      {activeTextSelection &&
        activeTextSelection.page_number === pageNumber &&
        selectionLabels && (
          <div data-reader-selection-toolbar>
            <ReaderSelectionToolbar
              labels={selectionLabels}
              onAsk={() => onAskSelection?.(activeTextSelection)}
              onComment={() => onCommentSelection?.(activeTextSelection)}
              onCopySettled={() => onActiveTextSelectionChange?.(undefined)}
              onHighlight={(color) =>
                onHighlightSelection?.(activeTextSelection, color)
              }
              selection={activeTextSelection}
            />
          </div>
        )}
    </article>
  );
}

export function PdfPage({
  adapter,
  annotationLinkLabel,
  fitMode,
  canvasLabel,
  onInternalDestination,
  onVisiblePageChange,
  pageCount,
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
  onVisiblePageChange: (pageNumber: number) => void;
  pageCount: number;
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
  const activePageRef = React.useRef(0);
  const [containerSize, setContainerSize] = React.useState({
    height: 0,
    width: 0,
  });
  const clearActiveSelection = React.useCallback(() => {
    onActiveTextSelectionChange?.(undefined);
    window.getSelection()?.removeAllRanges();
  }, [onActiveTextSelectionChange]);

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
    const container = containerRef.current;
    if (!container) return;
    const scrollContainer = container;
    let frame = 0;
    function updateVisiblePage() {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const viewport = scrollContainer.getBoundingClientRect();
        const pages = [
          ...scrollContainer.querySelectorAll<HTMLElement>(
            "[data-pdf-page-number]",
          ),
        ].map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            bottom: rect.bottom,
            pageNumber: Number(element.dataset.pdfPageNumber),
            top: rect.top,
          };
        });
        const nextPage = selectReaderViewportPage(viewport, pages);
        if (nextPage && nextPage !== activePageRef.current) {
          activePageRef.current = nextPage;
          onVisiblePageChange(nextPage);
        }
      });
    }
    updateVisiblePage();
    scrollContainer.addEventListener("scroll", updateVisiblePage, {
      passive: true,
    });
    return () => {
      window.cancelAnimationFrame(frame);
      scrollContainer.removeEventListener("scroll", updateVisiblePage);
    };
  }, [onVisiblePageChange]);

  React.useEffect(() => {
    if (activePageRef.current === pageNumber) return;
    const target = containerRef.current?.querySelector<HTMLElement>(
      `[data-pdf-page-number="${pageNumber}"]`,
    );
    if (!target) return;
    activePageRef.current = pageNumber;
    target.scrollIntoView({ behavior: "auto", block: "start" });
  }, [pageNumber]);

  return (
    <div
      aria-label={canvasLabel}
      className="bg-subtle relative min-h-0 flex-1 overflow-auto overscroll-contain p-4"
      onPointerDown={(event) => {
        const target = event.target as HTMLElement;
        if (!target.closest("[data-reader-selection-toolbar]")) {
          clearActiveSelection();
        }
      }}
      ref={containerRef}
      role="region"
      tabIndex={0}
    >
      <div className="grid min-w-max gap-4">
        {Array.from({ length: pageCount }, (_, index) => index + 1).map(
          (number) => (
            <PdfPageSurface
              activeTextSelection={activeTextSelection}
              adapter={adapter}
              annotationLinkLabel={annotationLinkLabel}
              annotations={annotations}
              containerSize={containerSize}
              currentPageNumber={pageNumber}
              fitMode={fitMode}
              key={number}
              loadingLabel={loadingLabel}
              onActiveTextSelectionChange={onActiveTextSelectionChange}
              onAnnotationSelect={onAnnotationSelect}
              onAskSelection={onAskSelection}
              onCommentSelection={onCommentSelection}
              onHighlightSelection={onHighlightSelection}
              onInternalDestination={onInternalDestination}
              pageNumber={number}
              scrollContainerRef={containerRef}
              searchQuery={searchQuery}
              selectedAnnotationId={selectedAnnotationId}
              selectionLabels={selectionLabels}
              zoom={zoom}
            />
          ),
        )}
      </div>
    </div>
  );
}
