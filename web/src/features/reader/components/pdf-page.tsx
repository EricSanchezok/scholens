"use client";

import type { PDFPageProxy } from "pdfjs-dist";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { PdfDocumentAdapter, renderPdfPage } from "../pdf-document-adapter";
import { readerPdfRectsForPage } from "../reader-pdf-position";
import {
  readerSelectionFocusPage,
  type ReaderSelection,
} from "../reader-selection";
import {
  readerHighlightColorValue,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";
import {
  readerScrollTopForTarget,
  type ReaderScrollContainerGeometry,
} from "../reader-scroll";
import type { ReaderSearchMatch } from "../reader-search";
import type {
  ReaderAnnotationAudience,
  ReaderAnnotationSummary,
} from "../reader-types";
import {
  ReaderSelectionToolbar,
  type ReaderSelectionLabels,
  type ReaderSelectionTranslationPreview,
} from "./reader-selection-toolbar";
import { type NormalizedSelectionRect } from "../selection/rect-normalization";
import {
  ensureEndOfContent,
  installTextLayerSelectionGuard,
  uninstallTextLayerSelectionGuard,
} from "../selection/text-layer-selection-guard";
import {
  createDocumentSelectionController,
  type CommittedDocumentSelection,
} from "../selection/document-selection-controller";
import { createReaderSelectionPageCoordinator } from "../selection/reader-selection-page-coordinator";

const EMPTY_SEARCH_MATCHES: ReaderSearchMatch[] = [];

export type ReaderFitMode = "width" | "page" | "custom";
export type { ReaderSelection } from "../reader-selection";
export type ReaderPdfSourceTarget = {
  page_number: number;
  source_rect: NormalizedSelectionRect;
};

export {
  coalesceSelectionRects,
  normalizeReaderSelectionRects,
} from "../selection/rect-normalization";

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

export function readerPdfSourceScrollTop({
  container,
  page,
  sourceRect,
}: {
  container: ReaderScrollContainerGeometry;
  page: { height: number; top: number };
  sourceRect: NormalizedSelectionRect;
}) {
  return readerScrollTopForTarget({
    alignment: "center",
    container,
    target: {
      height: sourceRect.height * page.height,
      top: page.top + sourceRect.y * page.height,
    },
  });
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

export function readerAnnotationPaintMode(
  annotations: ReaderAnnotationSummary[],
) {
  return countReaderAnnotationComments(annotations) > 0
    ? "annotation"
    : "highlight";
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
  pageErrorDescription,
  pageErrorTitle,
  downloadLabel,
  onDownload,
  onRenderError,
  annotations = [],
  selectedAnnotationId,
  previewAnnotationId,
  activeTextSelection,
  selectionLabels,
  onAnnotationSelect,
  onAskSelection,
  onCommentSelection,
  onHighlightSelection,
  onOpenTranslation,
  onTranslateSelection,
  onActiveTextSelectionChange,
  projectContext,
  translationPreview,
  sourceTarget,
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
  pageErrorDescription: string;
  pageErrorTitle: string;
  downloadLabel: string;
  onDownload: () => void;
  onRenderError?: (pageNumber: number, error: unknown) => void;
  annotations?: ReaderAnnotationSummary[];
  selectedAnnotationId?: string;
  previewAnnotationId?: string;
  activeTextSelection?: ReaderSelection;
  selectionLabels?: ReaderSelectionLabels;
  onAnnotationSelect?: (annotationId: string) => void;
  onAskSelection?: (selection: ReaderSelection) => void;
  onCommentSelection?: (selection: ReaderSelection) => void;
  onHighlightSelection?: (
    selection: ReaderSelection,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => void;
  onOpenTranslation?: () => void;
  onTranslateSelection?: (selection: ReaderSelection) => void;
  projectContext?: boolean;
  translationPreview?: ReaderSelectionTranslationPreview;
  sourceTarget?: ReaderPdfSourceTarget;
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
  const [renderErrorKey, setRenderErrorKey] = React.useState("");
  const reportedRenderErrorsRef = React.useRef(new Set<string>());

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
  const expectedRenderedKey = `${pageNumber}:${scale}:${searchQuery}:${activeSearchMatch?.id ?? ""}`;

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const textLayer = textLayerRef.current;
    const annotationLayer = annotationLayerRef.current;
    if (!shouldRender || !page || !canvas || !textLayer || !annotationLayer)
      return;
    let active = true;
    const renderTask = renderPdfPage({
      activeSearchMatchId: activeSearchMatch?.id,
      annotationLinkClassName: cn(
        focusSurfaceVariants({ intent: "neutral" }),
        "focus-visible:opacity-60 forced-colors:opacity-100",
      ),
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
        setRenderedKey(expectedRenderedKey);
        ensureEndOfContent(textLayer);
        if (activeSearchElement) {
          window.requestAnimationFrame(() => {
            const container = scrollContainerRef.current;
            if (!container) return;
            const containerRect = container.getBoundingClientRect();
            const targetRect = activeSearchElement.getBoundingClientRect();
            container.scrollTo({
              behavior: "auto",
              top: readerScrollTopForTarget({
                container: {
                  clientHeight: container.clientHeight,
                  scrollHeight: container.scrollHeight,
                  scrollTop: container.scrollTop,
                  top: containerRect.top,
                },
                target: { height: targetRect.height, top: targetRect.top },
                alignment: "center",
              }),
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
        if (!active) return;
        setRenderErrorKey(expectedRenderedKey);
        if (!reportedRenderErrorsRef.current.has(expectedRenderedKey)) {
          reportedRenderErrorsRef.current.add(expectedRenderedKey);
          onRenderError?.(pageNumber, error);
        }
      });
    return () => {
      active = false;
      renderTask.cancel();
    };
  }, [
    annotationLinkLabel,
    activeSearchMatch?.id,
    expectedRenderedKey,
    onInternalDestination,
    page,
    pageNumber,
    onRenderError,
    shouldRender,
    scale,
    scrollContainerRef,
    searchMatches,
    searchQuery,
  ]);

  const rendering =
    shouldRender &&
    renderErrorKey !== expectedRenderedKey &&
    (!page || renderedKey !== expectedRenderedKey);
  const renderError = renderErrorKey === expectedRenderedKey;

  React.useEffect(() => {
    const textLayer = textLayerRef.current;
    if (!textLayer) return;
    installTextLayerSelectionGuard(textLayer);
    return () => uninstallTextLayerSelectionGuard(textLayer);
  }, []);

  const pageAnnotations = annotations.filter((annotation) => {
    const position = annotation.position;
    return (
      position?.kind === "pdf_text" &&
      Boolean(readerPdfRectsForPage(position, pageNumber))
    );
  });
  const annotationGroups = groupReaderAnnotationsByAnchor(pageAnnotations);

  return (
    <article
      className={cn(
        "shadow-raised bg-surface relative mx-auto shrink-0",
        activeTextSelection?.anchor.kind === "pdf_text" &&
          readerPdfRectsForPage(activeTextSelection.anchor, pageNumber) &&
          "z-30",
      )}
      data-pdf-page-number={pageNumber}
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
      {renderError && (
        <div className="absolute inset-0 z-30 p-4">
          <AsyncFeedback
            action={{ label: downloadLabel, onClick: onDownload }}
            description={pageErrorDescription}
            presentation="overlay"
            state="error"
            title={pageErrorTitle}
          />
        </div>
      )}
      <canvas className="absolute inset-0" ref={canvasRef} />
      <div
        className="textLayer pdf-text-layer"
        data-pdf-text-ready={
          renderedKey === expectedRenderedKey ? "true" : undefined
        }
        ref={textLayerRef}
      />
      <div
        className="pdf-annotation-layer pointer-events-none absolute inset-0 [&_a]:pointer-events-auto"
        ref={annotationLayerRef}
      />
      <div className="pointer-events-none absolute inset-0 z-10">
        {annotationGroups.map((group) => {
          const annotation = group[0];
          const position = annotation?.position;
          if (!annotation || position?.kind !== "pdf_text") return null;
          const pageRects = readerPdfRectsForPage(position, pageNumber);
          if (!pageRects) return null;
          const groupSelected = group.some(
            (item) => item.id === selectedAnnotationId,
          );
          const groupPreviewed = group.some(
            (item) => item.id === previewAnnotationId,
          );
          const selectedGroupItem = group.find(
            (item) => item.id === selectedAnnotationId,
          );
          const previewGroupItem = group.find(
            (item) => item.id === previewAnnotationId,
          );
          const interactionTarget =
            previewGroupItem ?? selectedGroupItem ?? annotation;
          const commentCount = countReaderAnnotationComments(group);
          const paintMode = readerAnnotationPaintMode(group);
          const markerRect =
            position.page_number === pageNumber ? pageRects[0] : undefined;
          const resolved = group.every((item) => item.status === "resolved");
          const activateGroup = () =>
            onAnnotationSelect?.(interactionTarget.id);

          return (
            <React.Fragment key={annotation.id}>
              {pageRects.map((rect, index) => (
                <button
                  aria-label={`${annotation.quote_text}${group.length > 1 ? ` (${group.length})` : ""}`}
                  aria-pressed={groupSelected}
                  className={cn(
                    "motion-control pointer-events-auto absolute rounded-[1px]",
                    focusSurfaceVariants({ intent: "selection" }),
                    paintMode === "highlight" &&
                      "opacity-20 hover:opacity-30 focus-visible:opacity-30",
                    paintMode === "annotation" &&
                      "opacity-75 hover:opacity-100 focus-visible:opacity-100",
                    groupSelected &&
                      (paintMode === "highlight"
                        ? "opacity-30"
                        : "opacity-100"),
                    groupPreviewed &&
                      (paintMode === "highlight"
                        ? "opacity-40"
                        : "opacity-100"),
                    resolved && "opacity-20 grayscale",
                  )}
                  data-reader-annotation-count={group.length}
                  data-reader-annotation-highlight={interactionTarget.id}
                  data-reader-annotation-mode={paintMode}
                  data-reader-annotation-previewed={groupPreviewed || undefined}
                  data-reader-annotation-selected={groupSelected || undefined}
                  key={`${annotation.id}:${index}:${group.length}`}
                  onClick={activateGroup}
                  style={{
                    backgroundColor:
                      paintMode === "highlight"
                        ? readerHighlightColorValue(interactionTarget.color)
                        : "transparent",
                    borderBottomColor:
                      paintMode === "annotation"
                        ? readerHighlightColorValue(interactionTarget.color)
                        : undefined,
                    borderBottomStyle:
                      paintMode === "annotation" ? "solid" : undefined,
                    borderBottomWidth:
                      paintMode === "annotation"
                        ? groupSelected || groupPreviewed
                          ? "3px"
                          : "2px"
                        : undefined,
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
                    "shadow-raised text-caption border-line bg-surface text-secondary pointer-events-auto absolute right-2 z-20 inline-flex h-6 min-w-6 items-center justify-center gap-1 rounded-full border px-1.5 font-semibold",
                    resolved && "bg-subtle text-muted opacity-70 grayscale",
                    focusSurfaceVariants({ intent: "status" }),
                  )}
                  data-reader-annotation-comment-marker={interactionTarget.id}
                  onClick={activateGroup}
                  style={{
                    top: `${Math.min(Math.max(markerRect.y * 100, 1), 95)}%`,
                  }}
                  type="button"
                >
                  <span
                    aria-hidden
                    className="size-2 rounded-full"
                    style={{
                      backgroundColor: readerHighlightColorValue(
                        interactionTarget.color,
                      ),
                    }}
                  />
                  {commentCount}
                </button>
              ) : null}
            </React.Fragment>
          );
        })}
      </div>
      {activeTextSelection?.anchor.kind === "pdf_text" &&
      readerPdfRectsForPage(activeTextSelection.anchor, pageNumber) ? (
        <div
          className="pointer-events-none absolute inset-0 z-20"
          data-active-selection-overlay
        >
          <ReaderSelectionOverlay
            rects={readerPdfRectsForPage(
              activeTextSelection.anchor,
              pageNumber,
            )!}
          />
        </div>
      ) : null}
      {sourceTarget?.page_number === pageNumber ? (
        <div
          className="pointer-events-none absolute inset-0 z-20"
          data-reflow-source-overlay
        >
          <ReaderSelectionOverlay rects={[sourceTarget.source_rect]} />
        </div>
      ) : null}
      {activeTextSelection &&
        readerSelectionFocusPage(activeTextSelection) === pageNumber &&
        selectionLabels && (
          <div data-reader-selection-toolbar>
            <ReaderSelectionToolbar
              boundaryRef={scrollContainerRef}
              labels={selectionLabels}
              onAsk={() => onAskSelection?.(activeTextSelection)}
              onComment={() => onCommentSelection?.(activeTextSelection)}
              onCopySettled={() => onActiveTextSelectionChange?.(undefined)}
              onHighlight={(color, audience) =>
                onHighlightSelection?.(activeTextSelection, color, audience)
              }
              onOpenTranslation={() => onOpenTranslation?.()}
              onTranslate={() => onTranslateSelection?.(activeTextSelection)}
              projectContext={projectContext}
              selection={activeTextSelection}
              translationPreview={translationPreview}
            />
          </div>
        )}
    </article>
  );
}

export function PdfPage({
  adapter,
  annotationNavigation,
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
  pageErrorDescription,
  pageErrorTitle,
  downloadLabel,
  onDownload,
  onRenderError,
  annotations = [],
  selectedAnnotationId,
  previewAnnotationId,
  activeTextSelection,
  selectionLabels,
  onAnnotationSelect,
  onAskSelection,
  onCommentSelection,
  onHighlightSelection,
  onOpenTranslation,
  onTranslateSelection,
  onActiveTextSelectionChange,
  projectContext,
  translationPreview,
  sourceTarget,
  activityScrollContainerRef,
}: {
  adapter: PdfDocumentAdapter;
  annotationNavigation?: { id: string; request: number };
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
  pageErrorDescription: string;
  pageErrorTitle: string;
  downloadLabel: string;
  onDownload: () => void;
  onRenderError?: (pageNumber: number, error: unknown) => void;
  annotations?: ReaderAnnotationSummary[];
  selectedAnnotationId?: string;
  previewAnnotationId?: string;
  activeTextSelection?: ReaderSelection;
  selectionLabels?: ReaderSelectionLabels;
  onAnnotationSelect?: (annotationId: string) => void;
  onAskSelection?: (selection: ReaderSelection) => void;
  onCommentSelection?: (selection: ReaderSelection) => void;
  onHighlightSelection?: (
    selection: ReaderSelection,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => void;
  onOpenTranslation?: () => void;
  onTranslateSelection?: (selection: ReaderSelection) => void;
  projectContext?: boolean;
  translationPreview?: ReaderSelectionTranslationPreview;
  sourceTarget?: ReaderPdfSourceTarget;
  activityScrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  onActiveTextSelectionChange?: (
    selection: ReaderSelection | undefined,
  ) => void;
}) {
  const internalContainerRef = React.useRef<HTMLDivElement>(null);
  const containerRef = activityScrollContainerRef ?? internalContainerRef;
  const routePageRef = React.useRef(pageNumber);
  const activePageRef = React.useRef(0);
  const internallyReportedPagesRef = React.useRef<number[]>([]);
  const pendingGesturePageRef = React.useRef<number | undefined>(undefined);
  const pendingPageAlignmentRef = React.useRef<number | undefined>(undefined);
  const alignmentFrameRef = React.useRef(0);
  const selectionPageCoordinatorRef = React.useRef<
    ReturnType<typeof createReaderSelectionPageCoordinator> | undefined
  >(undefined);
  const [selectionAlignmentGuarded, setSelectionAlignmentGuarded] =
    React.useState(false);
  const [containerSize, setContainerSize] = React.useState({
    height: 0,
    width: 0,
  });
  const reportVisiblePage = React.useCallback(
    (nextPage: number) => {
      const reports = internallyReportedPagesRef.current;
      if (reports.at(-1) !== nextPage) reports.push(nextPage);
      onVisiblePageChange(nextPage);
    },
    [onVisiblePageChange],
  );
  const settleInternallyReportedPage = React.useCallback(
    (settledPage: number, acknowledged: boolean) => {
      const reports = internallyReportedPagesRef.current;
      const reportedIndex = reports.lastIndexOf(settledPage);
      if (reportedIndex < 0) return;
      if (acknowledged) {
        reports.splice(0, reportedIndex + 1);
      } else {
        reports.splice(reportedIndex, 1);
      }
    },
    [],
  );
  const clearActiveSelection = React.useCallback(() => {
    onActiveTextSelectionChange?.(undefined);
    window.getSelection()?.removeAllRanges();
  }, [onActiveTextSelectionChange]);

  React.useEffect(() => {
    routePageRef.current = pageNumber;
  }, [pageNumber]);

  React.useEffect(() => {
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: setSelectionAlignmentGuarded,
      onReportPage: reportVisiblePage,
      onSettleReport: settleInternallyReportedPage,
    });
    selectionPageCoordinatorRef.current = coordinator;
    return () => {
      coordinator.dispose();
      if (selectionPageCoordinatorRef.current === coordinator) {
        selectionPageCoordinatorRef.current = undefined;
      }
    };
  }, [reportVisiblePage, settleInternallyReportedPage]);

  React.useEffect(() => {
    const root = containerRef.current;
    if (!root || !onActiveTextSelectionChange) return;
    const controller = createDocumentSelectionController({
      root,
      onCommit: (selection: CommittedDocumentSelection) => {
        const firstSegment = selection.segments[0];
        if (!firstSegment) return;
        onActiveTextSelectionChange({
          anchor: {
            kind: "pdf_text",
            page_number: firstSegment.pageNumber,
            rects: firstSegment.rects,
            segments: selection.segments.map((segment) => ({
              page_number: segment.pageNumber,
              rects: segment.rects,
            })),
          },
          document_id: "",
          focus_page_number: selection.focusPageNumber,
          kind: "paper_selection",
          page_number: firstSegment.pageNumber,
          selected_text: selection.text,
        });
      },
      onGestureChange: (active) => {
        const coordinator = selectionPageCoordinatorRef.current;
        if (active) {
          pendingGesturePageRef.current = undefined;
          coordinator?.startGesture(routePageRef.current);
          return;
        }
        const pendingPage = pendingGesturePageRef.current;
        pendingGesturePageRef.current = undefined;
        coordinator?.finishGesture(pendingPage);
      },
    });
    return () => controller.dispose();
  }, [containerRef, onActiveTextSelectionChange]);

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
  }, [containerRef]);

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
          if (selectionPageCoordinatorRef.current?.isGuarded()) {
            pendingGesturePageRef.current = nextPage;
          } else {
            reportVisiblePage(nextPage);
          }
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
  }, [containerRef, reportVisiblePage]);

  React.useEffect(() => {
    const routeDecision =
      selectionPageCoordinatorRef.current?.routePageChanged(pageNumber) ??
      "continue";
    if (routeDecision !== "continue") return;
    const reportedIndex =
      internallyReportedPagesRef.current.lastIndexOf(pageNumber);
    if (reportedIndex >= 0) {
      internallyReportedPagesRef.current.splice(0, reportedIndex + 1);
      return;
    }
    // An unrelated route page is an explicit navigation request. Drop any
    // skipped scroll reports so they cannot suppress a later real navigation.
    internallyReportedPagesRef.current.length = 0;
    const externallyRequested = activePageRef.current !== pageNumber;
    const layoutPending = pendingPageAlignmentRef.current === pageNumber;
    if (!externallyRequested && !layoutPending) return;
    const container = containerRef.current;
    const target = container?.querySelector<HTMLElement>(
      `[data-pdf-page-number="${pageNumber}"]`,
    );
    if (!container || !target) return;
    pendingPageAlignmentRef.current = pageNumber;
    window.cancelAnimationFrame(alignmentFrameRef.current);
    activePageRef.current = pageNumber;
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    container.scrollTo({
      behavior: "auto",
      top: readerScrollTopForTarget({
        container: {
          clientHeight: container.clientHeight,
          scrollHeight: container.scrollHeight,
          scrollTop: container.scrollTop,
          top: containerRect.top,
        },
        target: { height: targetRect.height, top: targetRect.top },
        alignment: "start",
      }),
    });
    if (containerSize.height > 0 && containerSize.width > 0) {
      alignmentFrameRef.current = window.requestAnimationFrame(() => {
        if (pendingPageAlignmentRef.current === pageNumber) {
          pendingPageAlignmentRef.current = undefined;
        }
      });
    }
    return () => window.cancelAnimationFrame(alignmentFrameRef.current);
  }, [
    containerRef,
    containerSize.height,
    containerSize.width,
    pageNumber,
    selectionAlignmentGuarded,
  ]);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || !sourceTarget) return;
    const frame = window.requestAnimationFrame(() => {
      const page = container.querySelector<HTMLElement>(
        `[data-pdf-page-number="${sourceTarget.page_number}"]`,
      );
      if (!page) return;
      const containerRect = container.getBoundingClientRect();
      const pageRect = page.getBoundingClientRect();
      container.scrollTo({
        behavior: "auto",
        top: readerPdfSourceScrollTop({
          container: {
            clientHeight: container.clientHeight,
            scrollHeight: container.scrollHeight,
            scrollTop: container.scrollTop,
            top: containerRect.top,
          },
          page: { height: pageRect.height, top: pageRect.top },
          sourceRect: sourceTarget.source_rect,
        }),
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [containerRef, containerSize.height, containerSize.width, sourceTarget]);

  React.useEffect(() => {
    if (!annotationNavigation) return;
    const frame = window.requestAnimationFrame(() => {
      const container = containerRef.current;
      const target = [
        ...(container?.querySelectorAll<HTMLElement>(
          "[data-reader-annotation-highlight]",
        ) ?? []),
      ].find(
        (element) =>
          element.dataset.readerAnnotationHighlight === annotationNavigation.id,
      );
      if (!container || !target) return;
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      container.scrollTo({
        behavior: "auto",
        top: readerScrollTopForTarget({
          container: {
            clientHeight: container.clientHeight,
            scrollHeight: container.scrollHeight,
            scrollTop: container.scrollTop,
            top: containerRect.top,
          },
          target: { height: targetRect.height, top: targetRect.top },
          alignment: "center",
        }),
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [annotationNavigation, containerRef]);

  // Stable per-page match arrays: the page render effect depends on
  // `searchMatches`, so a fresh array identity on every parent render would
  // restart visible pages' text-layer renders (emptying the DOM mid-flight).
  const pageSearchMatches = React.useMemo(() => {
    const byPage = new Map<number, ReaderSearchMatch[]>();
    for (const match of searchMatches) {
      const matches = byPage.get(match.pageNumber) ?? [];
      matches.push(match);
      byPage.set(match.pageNumber, matches);
    }
    return byPage;
  }, [searchMatches]);

  return (
    <div
      aria-label={canvasLabel}
      className={cn(
        "bg-subtle relative min-h-0 flex-1 overflow-auto overscroll-contain p-4",
        focusSurfaceVariants({ intent: "scroll" }),
      )}
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
              pageErrorDescription={pageErrorDescription}
              pageErrorTitle={pageErrorTitle}
              downloadLabel={downloadLabel}
              onDownload={onDownload}
              onRenderError={onRenderError}
              onActiveTextSelectionChange={onActiveTextSelectionChange}
              onAnnotationSelect={onAnnotationSelect}
              onAskSelection={onAskSelection}
              onCommentSelection={onCommentSelection}
              onHighlightSelection={onHighlightSelection}
              onOpenTranslation={onOpenTranslation}
              onTranslateSelection={onTranslateSelection}
              onInternalDestination={onInternalDestination}
              pageNumber={number}
              projectContext={projectContext}
              searchMatches={
                pageSearchMatches.get(number) ?? EMPTY_SEARCH_MATCHES
              }
              activeSearchMatch={
                activeSearchMatch?.pageNumber === number
                  ? activeSearchMatch
                  : undefined
              }
              scrollContainerRef={containerRef}
              searchQuery={searchQuery}
              selectedAnnotationId={selectedAnnotationId}
              previewAnnotationId={previewAnnotationId}
              selectionLabels={selectionLabels}
              translationPreview={translationPreview}
              sourceTarget={sourceTarget}
              zoom={zoom}
            />
          ),
        )}
      </div>
    </div>
  );
}
