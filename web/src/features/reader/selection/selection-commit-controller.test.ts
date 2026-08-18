import { afterEach, describe, expect, it, vi } from "vitest";

import { buildPageTextGeometryIndex } from "./page-text-geometry";
import { createSelectionCommitController } from "./selection-commit-controller";
import { ensureEndOfContent } from "./text-layer-selection-guard";

// jsdom lacks setBaseAndExtent; polyfill it via Range so the sentinel
// recovery path is testable in the unit environment.
if (!window.getSelection()?.setBaseAndExtent) {
  Object.defineProperty(Selection.prototype, "setBaseAndExtent", {
    configurable: true,
    value: function setBaseAndExtent(
      this: Selection,
      anchorNode: Node,
      anchorOffset: number,
      focusNode: Node,
      focusOffset: number,
    ) {
      this.removeAllRanges();
      const range = document.createRange();
      range.setStart(anchorNode, anchorOffset);
      range.setEnd(focusNode, focusOffset);
      this.addRange(range);
    },
  });
}

function setClientRect(
  element: HTMLElement,
  rect: { height: number; left: number; top: number; width: number },
) {
  Object.defineProperty(element, "getBoundingClientRect", {
    configurable: true,
    value: () => rect,
  });
}

function makeTextLayer() {
  const layer = document.createElement("div");
  layer.className = "pdf-text-layer";
  const span = document.createElement("span");
  span.textContent = "The NLP landscape";
  setClientRect(span, { height: 20, left: 0, top: 0, width: 200 });
  layer.append(span);
  document.body.append(layer);
  return layer;
}

function makeSelection(layer: HTMLElement, start: number, end: number) {
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  const span = layer.querySelector("span")!;
  const range = document.createRange();
  range.setStart(span.firstChild!, start);
  range.setEnd(span.firstChild!, end);
  selection.addRange(range);
  return selection;
}

afterEach(() => {
  vi.restoreAllMocks();
  window.getSelection()?.removeAllRanges();
  document.body.replaceChildren();
});

describe("createSelectionCommitController", () => {
  it("commits a normalized selection and clears the browser selection", () => {
    const layer = makeTextLayer();
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      getIndex: () => index,
      onCommit: commit,
    });

    makeSelection(layer, 3, 8);
    controller.syncNow();

    expect(commit).toHaveBeenCalledTimes(1);
    const selection = commit.mock.calls[0]![0];
    expect(selection.text).toContain("NLP");
    expect(selection.rects).toHaveLength(1);
    expect(window.getSelection()?.isCollapsed).toBe(true);

    controller.dispose();
  });

  it("does not commit an empty selection", () => {
    const layer = makeTextLayer();
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      getIndex: () => index,
      onCommit: commit,
    });

    makeSelection(layer, 3, 3);
    controller.syncNow();

    expect(commit).not.toHaveBeenCalled();
    controller.dispose();
  });

  it("restores the last valid extent when the browser rewrites to the sentinel", () => {
    const layer = makeTextLayer();
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      getIndex: () => index,
      onCommit: commit,
    });

    makeSelection(layer, 0, 3);
    controller.syncNow();
    expect(commit).toHaveBeenCalledTimes(1);

    // Simulate a transient rewrite: collapsed element selection on the
    // sentinel (the browser landing on `.selecting` while dragging).
    const sentinel = document.createElement("div");
    sentinel.className = "endOfContent";
    layer.append(sentinel);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    const range = document.createRange();
    range.selectNodeContents(sentinel);
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));

    // The controller restored the previous extent.
    expect(window.getSelection()?.toString()).toBe("The");
    controller.dispose();
  });

  it("drops stale generation commits", () => {
    vi.useFakeTimers();
    const layer = makeTextLayer();
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      getIndex: () => index,
      onCommit: commit,
    });

    makeSelection(layer, 0, 3);
    controller.commitFromPointerUp({ x: 5, y: 5 });
    makeSelection(layer, 0, 5);
    controller.commitFromPointerUp({ x: 5, y: 5 });
    vi.advanceTimersByTime(200);

    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit.mock.calls[0]![0].text).toBe("The N");
    controller.dispose();
    vi.useRealTimers();
  });

  it("notifyTextLayerChanged keeps the sentinel in place", () => {
    const layer = makeTextLayer();
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const controller = createSelectionCommitController({
      textLayer: layer,
      getIndex: () => index,
      onCommit: vi.fn(),
    });
    ensureEndOfContent(layer);
    controller.notifyTextLayerChanged();

    expect(layer.querySelectorAll(".endOfContent")).toHaveLength(1);
    controller.dispose();
  });
});
