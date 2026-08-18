/**
 * Selection commit controller.
 *
 * Owns the transition from a live browser selection to the committed,
 * geometry-normalized selection:
 *
 * - Tracks the last valid DOM extent so a transient selection rewrite (the
 *   browser landing on the `.selecting` container / sentinel while dragging)
 *   is restored instead of committed as a huge collapsed range.
 * - Commits only after pointer-up, with an rAF + 100 ms settle and a
 *   generation counter so stale syncs are dropped; the pointer-up position
 *   feeds the dead-zone clamp.
 * - After a successful commit, clears the browser selection (the overlay then
 *   owns the visual) and reports the normalized selection upward.
 *
 * The 300 ms auto-translation debounce lives downstream in
 * `useReaderTranslation` and is deliberately untouched.
 */

import type {
  GeometryPoint,
  PageTextGeometryIndex,
} from "./page-text-geometry";
import {
  normalizePdfSelection,
  type NormalizedSelection,
} from "./normalize-pdf-selection";
import { ensureEndOfContent } from "./text-layer-selection-guard";

export const SELECTION_SETTLE_DELAY_MS = 100;

export type SelectionCommitControllerOptions = {
  /** Called when the user commits a new normalized selection. */
  onCommit?: (selection: NormalizedSelection) => void;
  /** Called when the controller is cleared (Escape / outside click / page change). */
  onClear?: () => void;
};

type PendingSync = {
  generation: number;
  timer: ReturnType<typeof setTimeout>;
};

function isElementSelectionOnSentinel(selection: Selection) {
  if (selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  if (!range.collapsed) return false;
  const node = range.startContainer;
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const element = node as Element;
  return (
    element.classList.contains("selecting") ||
    element.classList.contains("endOfContent") ||
    Boolean(element.closest(".endOfContent"))
  );
}

function isRangeInsideTextLayer(range: Range, textLayer: HTMLElement) {
  const ancestor =
    range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentElement
      : (range.commonAncestorContainer as Element | null);
  return Boolean(ancestor && textLayer.contains(ancestor));
}

export function createSelectionCommitController({
  textLayer,
  getIndex,
  onCommit,
  onClear,
}: {
  textLayer: HTMLElement;
  getIndex: () => PageTextGeometryIndex | undefined;
  onCommit?: (selection: NormalizedSelection) => void;
  onClear?: () => void;
}) {
  let lastValid:
    | {
        anchorNode: Node;
        anchorOffset: number;
        focusNode: Node;
        focusOffset: number;
      }
    | undefined;
  let lastCommitted: NormalizedSelection | undefined;
  let generation = 0;
  let pending: PendingSync | undefined;
  let disposed = false;
  let lastPointerPoint: GeometryPoint | undefined;

  function recordValidSelection(selection: Selection) {
    if (selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (range.collapsed) return;
    if (!isRangeInsideTextLayer(range, textLayer)) return;
    lastValid = {
      anchorNode: selection.anchorNode ?? range.startContainer,
      anchorOffset: selection.anchorOffset ?? range.startOffset,
      focusNode: selection.focusNode ?? range.endContainer,
      focusOffset: selection.focusOffset ?? range.endOffset,
    };
  }

  function commit() {
    if (disposed) return;
    pending = undefined;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return;
    }
    const range = selection.getRangeAt(0);
    if (!isRangeInsideTextLayer(range, textLayer)) return;
    const index = getIndex();
    if (!index) return;
    const normalized = normalizePdfSelection({
      index,
      range,
      previous: lastCommitted,
      pointerPoint: lastPointerPoint,
    });
    if (!normalized) return;
    recordValidSelection(selection);
    lastCommitted = normalized;
    onCommit?.(normalized);
    selection.removeAllRanges();
  }

  function scheduleSync() {
    if (disposed) return;
    generation += 1;
    const currentGeneration = generation;
    if (pending) clearTimeout(pending.timer);
    pending = {
      generation: currentGeneration,
      timer: setTimeout(() => {
        if (disposed || generation !== currentGeneration) return;
        commit();
      }, SELECTION_SETTLE_DELAY_MS),
    };
  }

  function handleSelectionChange() {
    if (disposed) return;
    const selection = window.getSelection();
    if (!selection) return;
    // Restore the last valid extent when the browser rewrote the selection
    // into a transient collapsed element selection on the sentinel/container.
    if (isElementSelectionOnSentinel(selection) && lastValid) {
      try {
        selection.setBaseAndExtent(
          lastValid.anchorNode,
          lastValid.anchorOffset,
          lastValid.focusNode,
          lastValid.focusOffset,
        );
        recordValidSelection(selection);
      } catch {
        // Ignore invalid extents; the next change event will re-evaluate.
      }
      return;
    }
    if (!selection.isCollapsed && selection.rangeCount > 0) {
      recordValidSelection(selection);
    }
  }

  function handlePointerUp(event: PointerEvent) {
    if (disposed) return;
    // Synthesized events (tests, assistive tech) may carry (0,0); only a
    // real pointer position should feed the dead-zone clamp.
    lastPointerPoint =
      event.clientX !== 0 || event.clientY !== 0
        ? { x: event.clientX, y: event.clientY }
        : undefined;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      return;
    }
    if (!isRangeInsideTextLayer(selection.getRangeAt(0), textLayer)) return;
    recordValidSelection(selection);
    scheduleSync();
  }

  // Capture-phase so releases outside the article still commit, and so the
  // commit runs before the guard's bubble-phase sentinel reset.
  document.addEventListener("pointerup", handlePointerUp, true);
  document.addEventListener("selectionchange", handleSelectionChange);

  return {
    clear() {
      if (disposed) return;
      if (pending) clearTimeout(pending.timer);
      pending = undefined;
      generation += 1;
      lastValid = undefined;
      lastCommitted = undefined;
      onClear?.();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      if (pending) clearTimeout(pending.timer);
      pending = undefined;
      document.removeEventListener("pointerup", handlePointerUp, true);
      document.removeEventListener("selectionchange", handleSelectionChange);
    },
    /** Public for tests and immediate commit paths. */
    syncNow() {
      commit();
    },
    /** Public for tests: simulate the pointer-up commit flow. */
    commitFromPointerUp(point: GeometryPoint) {
      lastPointerPoint = point;
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
        return;
      }
      if (!isRangeInsideTextLayer(selection.getRangeAt(0), textLayer)) return;
      recordValidSelection(selection);
      scheduleSync();
    },
    /** Public for tests: notify the controller that text layer DOM changed. */
    notifyTextLayerChanged() {
      ensureEndOfContent(textLayer);
    },
  };
}
