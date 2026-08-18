/**
 * Text layer selection guard.
 *
 * Ports the PDF.js TextLayerBuilder selection-sentinel behavior into a
 * Reader-owned singleton coordinator. The sentinel div makes the browser
 * expand a drag selection to the sentinel instead of the whole text layer,
 * preventing "slight expansion suddenly selects everything". The `.selecting`
 * class mirrors the official state machine and keeps annotation/link hit
 * targets out of the way while a selection is in progress.
 */

import { isModernSelectionBrowser } from "./selection-browser-support";

type GuardLayer = {
  div: HTMLElement;
  endOfContent: HTMLElement;
};

const layers = new Map<HTMLElement, GuardLayer>();
let globalListenerStarted = false;
let globalAbort: AbortController | undefined;

function createEndOfContent(): HTMLElement {
  const div = document.createElement("div");
  div.className = "endOfContent";
  return div;
}

function resetLayer(layer: GuardLayer) {
  layer.div.append(layer.endOfContent);
  layer.endOfContent.style.width = "";
  layer.endOfContent.style.height = "";
  layer.div.classList.remove("selecting");
}

function activeLayerForRange(range: Range): GuardLayer | undefined {
  for (const [div, layer] of layers) {
    if (range.intersectsNode(div)) return layer;
  }
  return undefined;
}

function ensureGlobalListener() {
  if (globalListenerStarted) return;
  globalListenerStarted = true;
  globalAbort = new AbortController();
  const signal = globalAbort.signal;

  let pointerDown = false;

  document.addEventListener(
    "pointerdown",
    () => {
      pointerDown = true;
    },
    { signal },
  );

  document.addEventListener(
    "pointerup",
    () => {
      pointerDown = false;
      layers.forEach((layer) => resetLayer(layer));
    },
    { signal },
  );

  window.addEventListener(
    "blur",
    () => {
      pointerDown = false;
      layers.forEach((layer) => resetLayer(layer));
    },
    { signal },
  );

  document.addEventListener(
    "keyup",
    () => {
      if (!pointerDown) {
        layers.forEach((layer) => resetLayer(layer));
      }
    },
    { signal },
  );

  let previousRange: Range | undefined;
  document.addEventListener(
    "selectionchange",
    () => {
      const selection = document.getSelection();
      if (!selection || selection.rangeCount === 0) {
        layers.forEach((layer) => resetLayer(layer));
        return;
      }
      const active = new Set<GuardLayer>();
      for (let i = 0; i < selection.rangeCount; i += 1) {
        const layer = activeLayerForRange(selection.getRangeAt(i));
        if (layer) active.add(layer);
      }
      layers.forEach((layer) => {
        if (active.has(layer)) {
          layer.div.classList.add("selecting");
        } else {
          resetLayer(layer);
        }
      });

      if (isModernSelectionBrowser()) return;

      // Legacy Chromium path: move the sentinel beside the drag anchor so a
      // downward drag never lands on the sentinel itself.
      const range = selection.getRangeAt(0);
      const layer = activeLayerForRange(range);
      if (!layer) return;
      const modifyStart =
        previousRange &&
        (range.compareBoundaryPoints(Range.END_TO_END, previousRange) === 0 ||
          range.compareBoundaryPoints(Range.START_TO_END, previousRange) === 0);
      let anchor = modifyStart ? range.startContainer : range.endContainer;
      if (anchor.nodeType === Node.TEXT_NODE) anchor = anchor.parentNode!;
      if (
        anchor instanceof HTMLElement &&
        anchor.classList.contains("highlight")
      ) {
        anchor = anchor.parentElement ?? anchor;
      }
      if (!modifyStart && range.endOffset === 0) {
        let current: Node | null = anchor;
        while (current) {
          while (!current.previousSibling && current.parentNode) {
            current = current.parentNode;
          }
          current = current.previousSibling;
          if (current && current.childNodes.length > 0) break;
        }
        if (current) anchor = current;
      }
      const parentLayer =
        anchor instanceof HTMLElement
          ? anchor.parentElement?.closest<HTMLElement>(".pdf-text-layer")
          : undefined;
      const guard = parentLayer ? layers.get(parentLayer) : undefined;
      if (guard) {
        guard.endOfContent.style.width = parentLayer!.style.width;
        guard.endOfContent.style.height = parentLayer!.style.height;
        guard.endOfContent.style.userSelect = "text";
        anchor.parentElement?.insertBefore(
          guard.endOfContent,
          modifyStart ? anchor : anchor.nextSibling,
        );
      }
      previousRange = range.cloneRange();
    },
    { signal },
  );
}

/**
 * Register a rendered text layer with the guard. Idempotent per layer.
 */
export function installTextLayerSelectionGuard(textLayer: HTMLElement) {
  if (layers.has(textLayer)) return;
  ensureGlobalListener();
  const endOfContent = createEndOfContent();
  textLayer.append(endOfContent);
  layers.set(textLayer, { div: textLayer, endOfContent });
}

/**
 * Remove a text layer from the guard and reset its sentinel. Safe to call
 * when the layer was never registered.
 */
export function uninstallTextLayerSelectionGuard(textLayer: HTMLElement) {
  const layer = layers.get(textLayer);
  if (!layer) return;
  resetLayer(layer);
  layer.endOfContent.remove();
  layers.delete(textLayer);
  if (layers.size === 0 && globalAbort) {
    globalAbort.abort();
    globalAbort = undefined;
    globalListenerStarted = false;
  }
}

/**
 * Ensure the sentinel exists and sits at the end of the text layer after a
 * render or search-highlight DOM rewrite. The sentinel is never a selectable
 * span so rebuilding the layer or replacing children keeps it intact.
 */
export function ensureEndOfContent(textLayer: HTMLElement) {
  const layer = layers.get(textLayer);
  if (layer) {
    // A replaceChildren() rewrite detaches the sentinel; re-append it so the
    // layer stays protected without creating a duplicate.
    textLayer.append(layer.endOfContent);
    return layer.endOfContent;
  }
  installTextLayerSelectionGuard(textLayer);
  return layers.get(textLayer)?.endOfContent;
}

/** True while any registered text layer is in the middle of a selection. */
export function isSelectingTextLayer(textLayer: HTMLElement) {
  return textLayer.classList.contains("selecting");
}
