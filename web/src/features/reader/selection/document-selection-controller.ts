import { normalizeReaderSelectionRects } from "./rect-normalization";
import {
  limitDocumentSelectionSegments,
  type DocumentSelectionSegment,
} from "./document-selection-geometry";

export const DOCUMENT_SELECTION_SETTLE_DELAY_MS = 100;

export type CommittedDocumentSelection = {
  focusPageNumber: number;
  segments: DocumentSelectionSegment[];
  text: string;
};

function textLayerForNode(root: HTMLElement, node: Node | null) {
  const element =
    node?.nodeType === Node.ELEMENT_NODE
      ? (node as Element)
      : node?.parentElement;
  const layer = element?.closest<HTMLElement>(".pdf-text-layer");
  return layer && root.contains(layer) ? layer : undefined;
}

function pageNumberForLayer(layer: HTMLElement) {
  const page = layer.closest<HTMLElement>("[data-pdf-page-number]");
  const pageNumber = Number(page?.dataset.pdfPageNumber);
  return Number.isInteger(pageNumber) && pageNumber > 0
    ? pageNumber
    : undefined;
}

function selectionRanges(selection: Selection) {
  const ranges: Range[] = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    ranges.push(selection.getRangeAt(index));
  }
  return ranges;
}

function selectedTextLayers(root: HTMLElement, ranges: Range[]): HTMLElement[] {
  const layers = [...root.querySelectorAll<HTMLElement>(".pdf-text-layer")];
  const selected = new Set<HTMLElement>();
  for (const range of ranges) {
    const startLayer = textLayerForNode(root, range.startContainer);
    const endLayer = textLayerForNode(root, range.endContainer);
    const startIndex = startLayer ? layers.indexOf(startLayer) : -1;
    const endIndex = endLayer ? layers.indexOf(endLayer) : -1;
    if (startIndex >= 0 && endIndex >= 0) {
      const first = Math.min(startIndex, endIndex);
      const last = Math.max(startIndex, endIndex);
      for (let index = first; index <= last; index += 1) {
        selected.add(layers[index]!);
      }
      continue;
    }
    for (const layer of layers) {
      if (range.intersectsNode(layer)) selected.add(layer);
    }
  }
  return layers.filter((layer) => selected.has(layer));
}

function clippedRangeForLayer(range: Range, layer: HTMLElement) {
  if (!range.intersectsNode(layer)) return undefined;
  const layerRange = document.createRange();
  layerRange.selectNodeContents(layer);
  const clipped = range.cloneRange();
  if (range.compareBoundaryPoints(Range.START_TO_START, layerRange) < 0) {
    clipped.setStart(layerRange.startContainer, layerRange.startOffset);
  }
  if (range.compareBoundaryPoints(Range.END_TO_END, layerRange) > 0) {
    clipped.setEnd(layerRange.endContainer, layerRange.endOffset);
  }
  return clipped.collapsed ? undefined : clipped;
}

function readDocumentSelection(
  root: HTMLElement,
  selection: Selection | null,
): CommittedDocumentSelection | undefined {
  if (
    !selection ||
    selection.rangeCount === 0 ||
    selection.isCollapsed ||
    !textLayerForNode(root, selection.anchorNode) ||
    !textLayerForNode(root, selection.focusNode)
  ) {
    return undefined;
  }

  const text = selection.toString().trim();
  if (!text) return undefined;

  const ranges = selectionRanges(selection);
  const segments: DocumentSelectionSegment[] = [];
  for (const layer of selectedTextLayers(root, ranges)) {
    const pageNumber = pageNumberForLayer(layer);
    if (!pageNumber) continue;
    const clientRects: DOMRect[] = [];
    for (const range of ranges) {
      const clipped = clippedRangeForLayer(range, layer);
      if (clipped) clientRects.push(...Array.from(clipped.getClientRects()));
    }
    if (clientRects.length === 0) continue;
    const rects = normalizeReaderSelectionRects(
      layer.getBoundingClientRect(),
      clientRects,
    );
    if (rects.length > 0) segments.push({ pageNumber, rects });
  }
  segments.sort((left, right) => left.pageNumber - right.pageNumber);
  if (segments.length === 0) return undefined;

  const focusLayer = textLayerForNode(root, selection.focusNode);
  const focusPageNumber = focusLayer && pageNumberForLayer(focusLayer);
  const boundedSegments = limitDocumentSelectionSegments(
    segments,
    focusPageNumber,
  );
  return {
    focusPageNumber: focusPageNumber ?? boundedSegments.at(-1)!.pageNumber,
    segments: boundedSegments,
    text,
  };
}

export function createDocumentSelectionController({
  root,
  onCommit,
  onGestureChange,
}: {
  root: HTMLElement;
  onCommit: (selection: CommittedDocumentSelection) => void;
  onGestureChange?: (active: boolean) => void;
}) {
  let lastValidSelection: CommittedDocumentSelection | undefined;
  let pointerSelecting = false;
  let generation = 0;
  let pendingFrame: number | undefined;
  let pendingSnapshotFrame: number | undefined;
  let pendingTimer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  function cancelPending() {
    generation += 1;
    if (pendingFrame !== undefined) {
      window.cancelAnimationFrame(pendingFrame);
      pendingFrame = undefined;
    }
    if (pendingTimer !== undefined) {
      clearTimeout(pendingTimer);
      pendingTimer = undefined;
    }
  }

  function cancelPendingSnapshot() {
    if (pendingSnapshotFrame === undefined) return;
    window.cancelAnimationFrame(pendingSnapshotFrame);
    pendingSnapshotFrame = undefined;
  }

  function currentSelection() {
    try {
      return readDocumentSelection(root, window.getSelection());
    } catch {
      // PDF.js can replace a text layer while the browser still owns a Range.
      return undefined;
    }
  }

  function commit() {
    if (disposed) return;
    pendingTimer = undefined;
    const nativeSelection = window.getSelection();
    const liveSelection = currentSelection();
    if (
      !liveSelection &&
      nativeSelection &&
      nativeSelection.rangeCount > 0 &&
      !nativeSelection.isCollapsed
    ) {
      // A live selection outside this document is intentional. Never revive a
      // stale PDF Range, which would snap the viewport back to an older page.
      lastValidSelection = undefined;
      return;
    }
    const committed = liveSelection ?? lastValidSelection;
    if (!committed) return;
    onCommit(committed);
    nativeSelection?.removeAllRanges();
    lastValidSelection = undefined;
  }

  function scheduleCommit() {
    if (disposed) return;
    cancelPending();
    const scheduledGeneration = generation;
    pendingFrame = window.requestAnimationFrame(() => {
      pendingFrame = undefined;
      pendingTimer = setTimeout(() => {
        if (disposed || generation !== scheduledGeneration) return;
        commit();
      }, DOCUMENT_SELECTION_SETTLE_DELAY_MS);
    });
  }

  function updateSnapshot() {
    const nextSelection = currentSelection();
    if (nextSelection) lastValidSelection = nextSelection;
    return nextSelection;
  }

  function handleSelectionChange() {
    if (disposed) return;
    if (pointerSelecting) {
      if (pendingSnapshotFrame !== undefined) return;
      pendingSnapshotFrame = window.requestAnimationFrame(() => {
        pendingSnapshotFrame = undefined;
        updateSnapshot();
      });
      return;
    }
    const nextSelection = updateSnapshot();
    if (nextSelection) scheduleCommit();
  }

  function handlePointerDown(event: PointerEvent) {
    cancelPending();
    cancelPendingSnapshot();
    lastValidSelection = undefined;
    const target = event.target;
    pointerSelecting =
      target instanceof Element &&
      Boolean(target.closest(".pdf-text-layer")) &&
      root.contains(target);
    if (pointerSelecting) onGestureChange?.(true);
  }

  function finishPointerGesture() {
    if (disposed) return;
    cancelPendingSnapshot();
    if (pointerSelecting) {
      pointerSelecting = false;
      onGestureChange?.(false);
    }
    const nextSelection = updateSnapshot();
    const nativeSelection = window.getSelection();
    if (
      !nextSelection &&
      nativeSelection &&
      nativeSelection.rangeCount > 0 &&
      !nativeSelection.isCollapsed
    ) {
      lastValidSelection = undefined;
    }
    if (nextSelection || lastValidSelection) scheduleCommit();
  }

  document.addEventListener("pointerdown", handlePointerDown, true);
  document.addEventListener("pointerup", finishPointerGesture, true);
  document.addEventListener("pointercancel", finishPointerGesture, true);
  document.addEventListener("selectionchange", handleSelectionChange);
  window.addEventListener("blur", finishPointerGesture);

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelPending();
      cancelPendingSnapshot();
      if (pointerSelecting) onGestureChange?.(false);
      pointerSelecting = false;
      lastValidSelection = undefined;
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("pointerup", finishPointerGesture, true);
      document.removeEventListener("pointercancel", finishPointerGesture, true);
      document.removeEventListener("selectionchange", handleSelectionChange);
      window.removeEventListener("blur", finishPointerGesture);
    },
    syncNow() {
      updateSnapshot();
      commit();
    },
  };
}
