import { afterEach, describe, expect, it, vi } from "vitest";

import { createDocumentSelectionController } from "./document-selection-controller";

const originalGetClientRects = Object.getOwnPropertyDescriptor(
  Range.prototype,
  "getClientRects",
);

function makeDocumentPages() {
  const root = document.createElement("div");
  const layers = ["Alpha one ", "Beta two"].map((text, index) => {
    const page = document.createElement("article");
    page.dataset.pdfPageNumber = String(index + 1);
    const layer = document.createElement("div");
    layer.className = "pdf-text-layer";
    const span = document.createElement("span");
    span.textContent = text;
    layer.append(span);
    page.append(layer);
    root.append(page);
    vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
      bottom: (index + 1) * 100,
      height: 100,
      left: 0,
      right: 100,
      top: index * 100,
      width: 100,
      x: 0,
      y: index * 100,
      toJSON: () => undefined,
    });
    return layer;
  });
  document.body.append(root);
  return { layers, root };
}

function selectAcross(layers: HTMLElement[]) {
  const range = document.createRange();
  range.setStart(layers[0]!.querySelector("span")!.firstChild!, 6);
  range.setEnd(layers[1]!.querySelector("span")!.firstChild!, 4);
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

describe("createDocumentSelectionController", () => {
  it("commits one exact quote with ordered geometry for every selected page", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value(this: Range) {
        const onSecondPage = this.toString().includes("Beta");
        return [
          {
            height: 10,
            left: onSecondPage ? 20 : 10,
            top: onSecondPage ? 110 : 10,
            width: 40,
          },
        ];
      },
    });
    const { layers, root } = makeDocumentPages();
    const commit = vi.fn();
    const controller = createDocumentSelectionController({
      root,
      onCommit: commit,
    });

    selectAcross(layers);
    controller.syncNow();

    expect(commit).toHaveBeenCalledWith({
      focusPageNumber: 2,
      segments: [
        {
          pageNumber: 1,
          rects: [{ height: 0.1, width: 0.4, x: 0.1, y: 0.1 }],
        },
        {
          pageNumber: 2,
          rects: [{ height: 0.1, width: 0.4, x: 0.2, y: 0.1 }],
        },
      ],
      text: "one Beta",
    });
    expect(window.getSelection()?.isCollapsed).toBe(true);
    controller.dispose();
  });

  it("keeps the gesture active until its selection has committed", () => {
    vi.useFakeTimers();
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 10, left: 10, top: 10, width: 40 }],
    });
    const { layers, root } = makeDocumentPages();
    const lifecycle: string[] = [];
    const controller = createDocumentSelectionController({
      root,
      onCommit: () => lifecycle.push("commit"),
      onGestureChange: (active) => lifecycle.push(active ? "start" : "finish"),
    });

    layers[0]!.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true }),
    );
    selectAcross(layers);
    layers[1]!.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));

    expect(lifecycle).toEqual(["start"]);
    vi.runAllTimers();
    expect(lifecycle).toEqual(["start", "commit", "finish"]);
    controller.dispose();
  });

  it("uses the last complete multi-page snapshot after a transient collapse", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value(this: Range) {
        const second = this.toString().includes("Beta");
        return [
          {
            height: 10,
            left: 10,
            top: second ? 110 : 10,
            width: 40,
          },
        ];
      },
    });
    const { layers, root } = makeDocumentPages();
    const commit = vi.fn();
    const controller = createDocumentSelectionController({
      root,
      onCommit: commit,
    });

    selectAcross(layers);
    document.dispatchEvent(new Event("selectionchange"));
    window.getSelection()?.collapse(layers[1]!, 0);
    controller.syncNow();

    expect(commit.mock.calls[0]?.[0].segments).toHaveLength(2);
    controller.dispose();
  });

  it("anchors the toolbar to the focus page for a reverse selection", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value(this: Range) {
        return [
          {
            height: 10,
            left: 10,
            top: this.toString().includes("Beta") ? 110 : 10,
            width: 40,
          },
        ];
      },
    });
    const { layers, root } = makeDocumentPages();
    const commit = vi.fn();
    const controller = createDocumentSelectionController({
      root,
      onCommit: commit,
    });
    const selection = window.getSelection()!;
    selection.collapse(layers[1]!.querySelector("span")!.firstChild!, 4);
    selection.extend(layers[0]!.querySelector("span")!.firstChild!, 6);

    controller.syncNow();

    expect(commit.mock.calls[0]?.[0].focusPageNumber).toBe(1);
    expect(commit.mock.calls[0]?.[0].segments).toHaveLength(2);
    controller.dispose();
  });

  it("never revives a stale PDF selection over a live foreign selection", () => {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [{ height: 10, left: 10, top: 10, width: 40 }],
    });
    const { layers, root } = makeDocumentPages();
    const outside = document.createElement("p");
    outside.textContent = "Outside text";
    document.body.append(outside);
    const commit = vi.fn();
    const controller = createDocumentSelectionController({
      root,
      onCommit: commit,
    });

    selectAcross(layers);
    document.dispatchEvent(new Event("selectionchange"));
    const range = document.createRange();
    range.setStart(outside.firstChild!, 0);
    range.setEnd(outside.firstChild!, 7);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    controller.syncNow();

    expect(commit).not.toHaveBeenCalled();
    expect(window.getSelection()?.toString()).toBe("Outside");
    controller.dispose();
  });
});
