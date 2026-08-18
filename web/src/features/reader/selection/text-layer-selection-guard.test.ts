import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ensureEndOfContent,
  installTextLayerSelectionGuard,
  isSelectingTextLayer,
  uninstallTextLayerSelectionGuard,
} from "./text-layer-selection-guard";

function makeTextLayer() {
  const layer = document.createElement("div");
  layer.className = "pdf-text-layer";
  const span = document.createElement("span");
  span.textContent = "Selectable";
  Object.defineProperty(span, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ height: 20, left: 0, top: 0, width: 100 }),
  });
  layer.append(span);
  document.body.append(layer);
  return layer;
}

afterEach(() => {
  vi.restoreAllMocks();
  window.getSelection()?.removeAllRanges();
  for (const layer of document.querySelectorAll<HTMLElement>(
    ".pdf-text-layer",
  )) {
    uninstallTextLayerSelectionGuard(layer);
  }
  document.body.replaceChildren();
});

describe("text-layer-selection-guard", () => {
  it("installs a sentinel at the end of the layer", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    const sentinel = layer.querySelector(".endOfContent");
    expect(sentinel).not.toBeNull();
    expect(layer.lastElementChild).toBe(sentinel);
  });

  it("is idempotent", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    installTextLayerSelectionGuard(layer);
    expect(layer.querySelectorAll(".endOfContent")).toHaveLength(1);
  });

  it("uninstall removes the sentinel and selecting class", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    layer.classList.add("selecting");
    uninstallTextLayerSelectionGuard(layer);
    expect(layer.querySelector(".endOfContent")).toBeNull();
    expect(layer.classList.contains("selecting")).toBe(false);
  });

  it("ensureEndOfContent re-appends the sentinel after a DOM rewrite", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    layer.replaceChildren();
    const sentinel = ensureEndOfContent(layer);
    expect(sentinel).not.toBeNull();
    expect(layer.querySelector(".endOfContent")).not.toBeNull();
  });

  it("tracks the selecting state", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    expect(isSelectingTextLayer(layer)).toBe(false);
    layer.classList.add("selecting");
    expect(isSelectingTextLayer(layer)).toBe(true);
  });

  it("marks the layer selecting as soon as a drag starts", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);

    layer.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));

    expect(layer.classList.contains("selecting")).toBe(true);
  });

  it("marks the layer selecting when a selection intersects it", () => {
    const layer = makeTextLayer();
    installTextLayerSelectionGuard(layer);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    const range = document.createRange();
    range.selectNodeContents(layer.querySelector("span")!);
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    expect(layer.classList.contains("selecting")).toBe(true);
  });

  it("guards every text layer intersected by a cross-page range", () => {
    const first = makeTextLayer();
    const second = makeTextLayer();
    installTextLayerSelectionGuard(first);
    installTextLayerSelectionGuard(second);
    const selection = window.getSelection()!;
    const range = document.createRange();
    range.setStart(first.querySelector("span")!.firstChild!, 0);
    range.setEnd(second.querySelector("span")!.firstChild!, 3);
    selection.removeAllRanges();
    selection.addRange(range);

    document.dispatchEvent(new Event("selectionchange"));

    expect(first.classList.contains("selecting")).toBe(true);
    expect(second.classList.contains("selecting")).toBe(true);
  });
});
