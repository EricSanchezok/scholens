/** Commit a stable, single-page browser Range after pointer release. */

export const SELECTION_SETTLE_DELAY_MS = 100;

export type CommittedTextSelection = {
  rects: Array<{ height: number; left: number; top: number; width: number }>;
  text: string;
};

function isRangeInside(range: Range, textLayer: HTMLElement) {
  return (
    !range.collapsed &&
    textLayer.contains(range.startContainer) &&
    textLayer.contains(range.endContainer)
  );
}

export function createSelectionCommitController({
  textLayer,
  onCommit,
}: {
  textLayer: HTMLElement;
  onCommit: (selection: CommittedTextSelection) => void;
}) {
  let lastValidRange: Range | undefined;
  let generation = 0;
  let pendingFrame: number | undefined;
  let pendingTimer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  function currentValidRange() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return undefined;
    }
    const range = selection.getRangeAt(0);
    return isRangeInside(range, textLayer) ? range : undefined;
  }

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

  function commit() {
    if (disposed) return;
    pendingTimer = undefined;
    const liveSelection = window.getSelection();
    const liveRange = currentValidRange();
    // A non-collapsed Range outside this page is not a transient browser
    // collapse. It can be an intentional cross-page selection, so falling
    // back to this page's last Range would visibly snap the selection back.
    if (
      !liveRange &&
      liveSelection &&
      liveSelection.rangeCount > 0 &&
      !liveSelection.isCollapsed
    ) {
      lastValidRange = undefined;
      return;
    }
    const range = liveRange ?? lastValidRange;
    if (!range || !isRangeInside(range, textLayer)) return;
    let committed: CommittedTextSelection;
    try {
      const text = range.toString().trim();
      const rects = Array.from(range.getClientRects(), (rect) => ({
        height: rect.height,
        left: rect.left,
        top: rect.top,
        width: rect.width,
      }));
      if (!text || rects.length === 0) return;
      committed = { rects, text };
    } catch {
      // A text-layer render can detach Range boundaries during the settle
      // window. The next gesture starts from a fresh browser selection.
      lastValidRange = undefined;
      return;
    }
    onCommit(committed);
    window.getSelection()?.removeAllRanges();
    lastValidRange = undefined;
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
      }, SELECTION_SETTLE_DELAY_MS);
    });
  }

  function handleSelectionChange() {
    if (disposed) return;
    const range = currentValidRange();
    if (range) lastValidRange = range.cloneRange();
  }

  function handlePointerDown() {
    cancelPending();
    lastValidRange = undefined;
  }

  function handlePointerUp() {
    if (disposed) return;
    const range = currentValidRange();
    const selection = window.getSelection();
    if (range) {
      lastValidRange = range.cloneRange();
    } else if (
      selection &&
      selection.rangeCount > 0 &&
      !selection.isCollapsed
    ) {
      lastValidRange = undefined;
    }
    if (lastValidRange) scheduleCommit();
  }

  document.addEventListener("pointerdown", handlePointerDown, true);
  document.addEventListener("pointerup", handlePointerUp, true);
  document.addEventListener("selectionchange", handleSelectionChange);

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelPending();
      lastValidRange = undefined;
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("pointerup", handlePointerUp, true);
      document.removeEventListener("selectionchange", handleSelectionChange);
    },
    scheduleNow() {
      handlePointerUp();
    },
    syncNow() {
      const range = currentValidRange();
      if (range) lastValidRange = range.cloneRange();
      commit();
    },
  };
}
