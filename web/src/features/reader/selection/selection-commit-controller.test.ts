import { afterEach, describe, expect, it, vi } from "vitest";

import { createSelectionCommitController } from "./selection-commit-controller";

const originalGetClientRects = Object.getOwnPropertyDescriptor(
  Range.prototype,
  "getClientRects",
);

function makeTextLayer() {
  const layer = document.createElement("div");
  layer.className = "pdf-text-layer";
  const span = document.createElement("span");
  span.textContent = "The NLP landscape";
  layer.append(span);
  document.body.append(layer);
  return layer;
}

function select(layer: HTMLElement, start: number, end: number) {
  const text = layer.querySelector("span")!.firstChild!;
  const range = document.createRange();
  range.setStart(text, start);
  range.setEnd(text, end);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.getSelection()?.removeAllRanges();
  document.body.replaceChildren();
  if (originalGetClientRects) {
    Object.defineProperty(
      Range.prototype,
      "getClientRects",
      originalGetClientRects,
    );
  } else {
    Reflect.deleteProperty(Range.prototype, "getClientRects");
  }
});

describe("createSelectionCommitController", () => {
  it("commits exact partial-span text and Range geometry", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 20, left: 30, top: 10, width: 35 }],
    });
    const layer = makeTextLayer();
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      onCommit: commit,
    });

    select(layer, 4, 7);
    controller.syncNow();

    expect(commit).toHaveBeenCalledWith({
      rects: [{ height: 20, left: 30, top: 10, width: 35 }],
      text: "NLP",
    });
    expect(window.getSelection()?.isCollapsed).toBe(true);
    controller.dispose();
  });

  it("uses the last valid Range if the browser transiently collapses", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 20, left: 0, top: 0, width: 30 }],
    });
    const layer = makeTextLayer();
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      onCommit: commit,
    });

    select(layer, 0, 3);
    document.dispatchEvent(new Event("selectionchange"));
    window.getSelection()?.collapse(layer, layer.childNodes.length);
    controller.syncNow();

    expect(commit.mock.calls[0]?.[0].text).toBe("The");
    controller.dispose();
  });

  it("drops stale scheduled commits and keeps the latest Range", () => {
    vi.useFakeTimers();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      return window.setTimeout(() => callback(0), 0);
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
      window.clearTimeout(id);
    });
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 20, left: 0, top: 0, width: 50 }],
    });
    const layer = makeTextLayer();
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      onCommit: commit,
    });

    select(layer, 0, 3);
    controller.scheduleNow();
    select(layer, 0, 5);
    controller.scheduleNow();
    vi.runAllTimers();

    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit.mock.calls[0]?.[0].text).toBe("The N");
    controller.dispose();
  });

  it("ignores collapsed and cross-layer selections", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 20, left: 0, top: 0, width: 30 }],
    });
    const layer = makeTextLayer();
    const other = makeTextLayer();
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: layer,
      onCommit: commit,
    });

    select(layer, 2, 2);
    controller.syncNow();
    const range = document.createRange();
    range.setStart(layer.querySelector("span")!.firstChild!, 0);
    range.setEnd(other.querySelector("span")!.firstChild!, 3);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    controller.syncNow();

    expect(commit).not.toHaveBeenCalled();
    controller.dispose();
  });

  it("does not replace an intentional cross-page Range with a stale page Range", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 20, left: 0, top: 0, width: 30 }],
    });
    const firstPage = makeTextLayer();
    const secondPage = makeTextLayer();
    const commit = vi.fn();
    const controller = createSelectionCommitController({
      textLayer: firstPage,
      onCommit: commit,
    });

    select(firstPage, 0, 3);
    document.dispatchEvent(new Event("selectionchange"));

    const range = document.createRange();
    range.setStart(firstPage.querySelector("span")!.firstChild!, 0);
    range.setEnd(secondPage.querySelector("span")!.firstChild!, 3);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    controller.syncNow();

    expect(commit).not.toHaveBeenCalled();
    expect(window.getSelection()?.toString()).toContain("The");
    controller.dispose();
  });
});
