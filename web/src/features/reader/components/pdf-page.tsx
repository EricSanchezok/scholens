"use client";

import type { PDFPageProxy } from "pdfjs-dist";
import * as React from "react";

import { LoadingState } from "@/components/feedback";
import { keyboardFocusRing } from "@/components/ui";
import { CommentIcon } from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { PdfDocumentAdapter, renderPdfPage } from "../pdf-document-adapter";
import {
  readerHighlightColorValue,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";
import type { ReaderSearchMatch } from "../reader-search";
import type {
  ReaderAnnotationAudience,
  ReaderAnnotationSummary,
} from "../reader-types";
import {
  ReaderSelectionToolbar,
  type ReaderSelectionLabels,
} from "./reader-selection-toolbar";

export type ReaderFitMode = "width" | "page" | "custom";
export type ReaderSelection =
  components["schemas"]["PaperSelectionTurnContext"];

type SelectionRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

type NormalizedSelectionRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

function coalesceSelectionRects(rects: SelectionRect[]) {
  const merged: SelectionRect[] = [];

  for (const rect of rects.sort(
    (left, right) => left.top - right.top || left.left - right.left,
  )) {
    const match = merged.find((candidate) => {
      const verticalOverlap = Math.max(
        0,
        Math.min(candidate.top + candidate.height, rect.top + rect.height) -
          Math.max(candidate.top, rect.top),
      );
      const overlapRatio =
        verticalOverlap / Math.min(candidate.height, rect.height);
      const horizontalGap = Math.max(
        0,
        rect.left - (candidate.left + candidate.width),
        candidate.left - (rect.left + rect.width),
      );
      return (
        overlapRatio >= 0.55 &&
        horizontalGap <=
          Math.max(2, Math.min(candidate.height, rect.height) / 2)
      );
    });

    if (!match) {
      merged.push({ ...rect });
      continue;
    }

    const right = Math.max(match.left + match.width, rect.left + rect.width);
    const bottom = Math.max(match.top + match.height, rect.top + rect.height);
    match.left = Math.min(match.left, rect.left);
    match.top = Math.min(match.top, rect.top);
    match.width = right - match.left;
    match.height = bottom - match.top;
  }

  return merged;
}

export function normalizeReaderSelectionRects(
  pageRect: SelectionRect,
  clientRects: SelectionRect[],
): NormalizedSelectionRect[] {
  if (pageRect.width <= 0 || pageRect.height <= 0) return [];
  const pageRight = pageRect.left + pageRect.width;
  const pageBottom = pageRect.top + pageRect.height;
  const containmentTolerance = 1;
  const clippedRects = clientRects
    .filter((rect) => {
      const rectRight = rect.left + rect.width;
      const rectBottom = rect.top + rect.height;
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        rect.width < pageRect.width &&
        rect.height < pageRect.height &&
        rect.left >= pageRect.left - containmentTolerance &&
        rect.top >= pageRect.top - containmentTolerance &&
        rectRight <= pageRight + containmentTolerance &&
        rectBottom <= pageBottom + containmentTolerance
      );
    })
    .map((rect) => ({
      left: Math.max(pageRect.left, Math.min(pageRight, rect.left)),
      top: Math.max(pageRect.top, Math.min(pageBottom, rect.top)),
      width:
        Math.max(pageRect.left, Math.min(pageRight, rect.left + rect.width)) -
        Math.max(pageRect.left, Math.min(pageRight, rect.left)),
      height:
        Math.max(pageRect.top, Math.min(pageBottom, rect.top + rect.height)) -
        Math.max(pageRect.top, Math.min(pageBottom, rect.top)),
    }))
    .filter((rect) => rect.width > 0 && rect.height > 0);

  return coalesceSelectionRects(clippedRects).map((rect) => ({
    x: (rect.left - pageRect.left) / pageRect.width,
    y: (rect.top - pageRect.top) / pageRect.height,
    width: rect.width / pageRect.width,
    height: rect.height / pageRect.height,
  }));
}

function ReaderSelectionOverlay({
  rects,
}: {
  rects: NormalizedSelectionRect[];
}) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    function paintSelection() {
      if (!canvas) return;
      const bounds = canvas.getBoundingClientRect();
      if (bounds.width <= 0 || bounds.height <= 0) return;
      const pixelRatio = window.devicePixelRatio || 1;
      canvas.width = Math.round(bounds.width * pixelRatio);
      canvas.height = Math.round(bounds.height * pixelRatio);
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      const selectionPath = new Path2D();
      for (const rect of rects) {
        selectionPath.rect(
          rect.x * bounds.width,
          rect.y * bounds.height,
          rect.width * bounds.width,
          rect.height * bounds.height,
        );
      }
      context.fillStyle = getComputedStyle(canvas).color;
      context.fill(selectionPath);
    }

    paintSelection();
    const observer = new ResizeObserver(paintSelection);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [rects]);

  return (
    <canvas
      aria-hidden="true"
      className="pdf-selection-overlay absolute inset-0 size-full"
      ref={canvasRef}
    />
  );
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

export function groupReaderAnnotationsByAnchor(
  annotations: ReaderAnnotationSummary[],
): ReaderAnnotationSummary[][] {
  return [
    ...annotations
      .reduce((groups, annotation) => {
        const position = annotation.position;
        const key = JSON.stringify(position ?? { id: annotation.id });
        groups.set(key, [...(groups.get(key) ?? []), annotation]);
        return groups;
      }, new Map<string, ReaderAnnotationSummary[]>())
      .values(),
  ];
}

export function countReaderAnnotationComments(
  annotations: ReaderAnnotationSummary[],
) {
  return annotations.reduce(
    (count, annotation) => count + annotation.comment_count,
    0,
  );
}

function PdfPageSurface({
  adapter,
  annotationLinkLabel,
  annotationCommentLabel,
  fitMode,
  containerSize,
  currentPageNumber,
  onInternalDestination,
  pageNumber,
  searchMatches,
  activeSearchMatch,
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
  projectContext,
}: {
  adapter: PdfDocumentAdapter;
  annotationLinkLabel: string;
  annotationCommentLabel: (count: number) => string;
  containerSize: { height: number; width: number };
  currentPageNumber: number;
  fitMode: ReaderFitMode;
  onInternalDestination: (destination: unknown) => void;
  pageNumber: number;
  searchMatches: ReaderSearchMatch[];
  activeSearchMatch?: ReaderSearchMatch;
  searchQuery: string;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  zoom: number;
  loadingLabel: string;
  annotations?: ReaderAnnotationSummary[];
  selectedAnnotationId?: string;
  activeTextSelection?: ReaderSelection;
  selectionLabels?: ReaderSelectionLabels;
  onAnnotationSelect?: (annotationId: string, anchorIds: string[]) => void;
  onAskSelection?: (selection: ReaderSelection) => void;
  onCommentSelection?: (selection: ReaderSelection) => void;
  onHighlightSelection?: (
    selection: ReaderSelection,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => void;
  projectContext?: boolean;
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

  React.useEffect(() => {
    if (searchMatches.length > 0) return;
    const textLayer = textLayerRef.current;
    if (!textLayer) return;
    for (const highlight of textLayer.querySelectorAll<HTMLElement>(
      ".pdf-search-match",
    )) {
      highlight.replaceWith(
        document.createTextNode(highlight.textContent ?? ""),
      );
    }
    for (const textItem of textLayer.children) textItem.normalize();
  }, [searchMatches.length]);

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
      activeSearchMatchId: activeSearchMatch?.id,
      annotationLinkLabel,
      annotationLayer,
      canvas,
      onInternalDestination,
      page,
      scale,
      searchMatches,
      textLayer,
    });
    void renderTask.promise
      .then(({ activeSearchElement }) => {
        if (!active) return;
        setRenderedKey(
          `${pageNumber}:${scale}:${searchQuery}:${activeSearchMatch?.id ?? ""}`,
        );
        if (activeSearchElement) {
          window.requestAnimationFrame(() => {
            activeSearchElement.scrollIntoView({
              behavior: "auto",
              block: "center",
              inline: "nearest",
            });
          });
        }
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
    activeSearchMatch?.id,
    onInternalDestination,
    page,
    pageNumber,
    shouldRender,
    scale,
    searchMatches,
    searchQuery,
  ]);

  const rendering =
    shouldRender &&
    (!page ||
      renderedKey !==
        `${pageNumber}:${scale}:${searchQuery}:${activeSearchMatch?.id ?? ""}`);

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
      const pageRect = textLayer.getBoundingClientRect();
      const rects = normalizeReaderSelectionRects(pageRect, [
        ...range.getClientRects(),
      ]);
      const selectedText = browserSelection.toString().trim();
      if (!selectedText || rects.length === 0) return;
      browserSelection.removeAllRanges();
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
    const position = annotation.position;
    return position?.kind === "pdf_text" && position.page_number === pageNumber;
  });
  const annotationGroups = groupReaderAnnotationsByAnchor(pageAnnotations);

  return (
    <article
      className={cn(
        "shadow-raised bg-surface relative mx-auto shrink-0",
        activeTextSelection?.page_number === pageNumber && "z-30",
      )}
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
      <div className="textLayer pdf-text-layer" ref={textLayerRef} />
      <div
        className="pdf-annotation-layer pointer-events-none absolute inset-0 [&_a]:pointer-events-auto [&_a]:outline-offset-2"
        ref={annotationLayerRef}
      />
      <div className="pointer-events-none absolute inset-0 z-10">
        {annotationGroups.map((group) => {
          const annotation = group[0];
          const position = annotation?.position;
          if (!annotation || position?.kind !== "pdf_text") return null;
          const groupSelected = group.some(
            (item) => item.id === selectedAnnotationId,
          );
          const selectedGroupItem = group.find(
            (item) => item.id === selectedAnnotationId,
          );
          const interactionTarget = selectedGroupItem ?? annotation;
          const anchorIds = group.map((item) => item.id);
          const commentCount = countReaderAnnotationComments(group);
          const markerRect = position.rects[0];
          const resolved = group.every((item) => item.status === "resolved");
          const activateGroup = () =>
            onAnnotationSelect?.(interactionTarget.id, anchorIds);

          return (
            <React.Fragment key={annotation.id}>
              {position.rects.map((rect, index) => (
                <button
                  aria-label={`${annotation.quote_text}${group.length > 1 ? ` (${group.length})` : ""}`}
                  className={cn(
                    "pointer-events-auto absolute rounded-[1px] opacity-40 transition-opacity hover:opacity-55 focus-visible:opacity-60",
                    keyboardFocusRing,
                    groupSelected && "opacity-60",
                    resolved && "opacity-20 grayscale",
                  )}
                  data-reader-annotation-count={group.length}
                  data-reader-annotation-highlight={interactionTarget.id}
                  data-reader-annotation-selected={groupSelected || undefined}
                  key={`${annotation.id}:${index}:${group.length}`}
                  onClick={activateGroup}
                  style={{
                    backgroundColor: readerHighlightColorValue(
                      interactionTarget.color,
                    ),
                    height: `${rect.height * 100}%`,
                    left: `${rect.x * 100}%`,
                    top: `${rect.y * 100}%`,
                    width: `${rect.width * 100}%`,
                  }}
                  type="button"
                />
              ))}
              {commentCount > 0 && markerRect ? (
                <button
                  aria-label={annotationCommentLabel(commentCount)}
                  className={cn(
                    "shadow-raised text-caption pointer-events-auto absolute right-2 z-20 inline-flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-full px-1.5 font-semibold",
                    resolved
                      ? "border-line bg-subtle text-muted border"
                      : "bg-foreground text-canvas",
                    keyboardFocusRing,
                  )}
                  data-reader-annotation-comment-marker={interactionTarget.id}
                  onClick={activateGroup}
                  style={{
                    top: `${Math.min(Math.max(markerRect.y * 100, 1), 95)}%`,
                  }}
                  type="button"
                >
                  <Icon glyph={CommentIcon} size={16} />
                  {commentCount}
                </button>
              ) : null}
            </React.Fragment>
          );
        })}
      </div>
      {activeTextSelection?.page_number === pageNumber &&
      activeTextSelection.anchor.kind === "pdf_text" ? (
        <div
          className="pointer-events-none absolute inset-0 z-20"
          data-active-selection-overlay
        >
          <ReaderSelectionOverlay rects={activeTextSelection.anchor.rects} />
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
              onHighlight={(color, audience) =>
                onHighlightSelection?.(activeTextSelection, color, audience)
              }
              projectContext={projectContext}
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
  annotationCommentLabel,
  fitMode,
  canvasLabel,
  onInternalDestination,
  onVisiblePageChange,
  pageCount,
  pageNumber,
  searchMatches,
  activeSearchMatch,
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
  projectContext,
}: {
  adapter: PdfDocumentAdapter;
  annotationLinkLabel: string;
  annotationCommentLabel: (count: number) => string;
  canvasLabel: string;
  fitMode: ReaderFitMode;
  onInternalDestination: (destination: unknown) => void;
  onVisiblePageChange: (pageNumber: number) => void;
  pageCount: number;
  pageNumber: number;
  searchMatches: ReaderSearchMatch[];
  activeSearchMatch?: ReaderSearchMatch;
  searchQuery: string;
  zoom: number;
  loadingLabel: string;
  annotations?: ReaderAnnotationSummary[];
  selectedAnnotationId?: string;
  activeTextSelection?: ReaderSelection;
  selectionLabels?: ReaderSelectionLabels;
  onAnnotationSelect?: (annotationId: string, anchorIds: string[]) => void;
  onAskSelection?: (selection: ReaderSelection) => void;
  onCommentSelection?: (selection: ReaderSelection) => void;
  onHighlightSelection?: (
    selection: ReaderSelection,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => void;
  projectContext?: boolean;
  onActiveTextSelectionChange?: (
    selection: ReaderSelection | undefined,
  ) => void;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const activePageRef = React.useRef(0);
  const pendingPageAlignmentRef = React.useRef<number | undefined>(undefined);
  const alignmentFrameRef = React.useRef(0);
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
        if (pendingPageAlignmentRef.current !== undefined) return;
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
    const externallyRequested = activePageRef.current !== pageNumber;
    const layoutPending = pendingPageAlignmentRef.current === pageNumber;
    if (!externallyRequested && !layoutPending) return;
    const target = containerRef.current?.querySelector<HTMLElement>(
      `[data-pdf-page-number="${pageNumber}"]`,
    );
    if (!target) return;
    pendingPageAlignmentRef.current = pageNumber;
    window.cancelAnimationFrame(alignmentFrameRef.current);
    activePageRef.current = pageNumber;
    target.scrollIntoView({ behavior: "auto", block: "start" });
    if (containerSize.height > 0 && containerSize.width > 0) {
      alignmentFrameRef.current = window.requestAnimationFrame(() => {
        if (pendingPageAlignmentRef.current === pageNumber) {
          pendingPageAlignmentRef.current = undefined;
        }
      });
    }
    return () => window.cancelAnimationFrame(alignmentFrameRef.current);
  }, [containerSize.height, containerSize.width, pageNumber]);

  React.useEffect(() => {
    if (!selectedAnnotationId) return;
    const frame = window.requestAnimationFrame(() => {
      const target = [
        ...(containerRef.current?.querySelectorAll<HTMLElement>(
          "[data-reader-annotation-highlight]",
        ) ?? []),
      ].find(
        (element) =>
          element.dataset.readerAnnotationHighlight === selectedAnnotationId,
      );
      target?.scrollIntoView({
        behavior: "auto",
        block: "center",
        inline: "nearest",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [containerSize.height, containerSize.width, selectedAnnotationId]);

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
              annotationCommentLabel={annotationCommentLabel}
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
              projectContext={projectContext}
              searchMatches={searchMatches.filter(
                (match) => match.pageNumber === number,
              )}
              activeSearchMatch={
                activeSearchMatch?.pageNumber === number
                  ? activeSearchMatch
                  : undefined
              }
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
