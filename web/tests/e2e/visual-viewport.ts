import type { Page } from "@playwright/test";

type ViewportMetrics = {
  height: number;
  offsetTop: number;
};

export async function mockVisualViewport(page: Page, initial: ViewportMetrics) {
  await page.addInitScript((metrics) => {
    const viewport = window.visualViewport;
    if (!viewport) return;

    let current = metrics;
    Object.defineProperty(viewport, "height", {
      configurable: true,
      get: () => current.height,
    });
    Object.defineProperty(viewport, "offsetTop", {
      configurable: true,
      get: () => current.offsetTop,
    });
    Object.defineProperty(window, "__setVisualViewportForTest", {
      configurable: true,
      value: (next: ViewportMetrics) => {
        current = next;
        viewport.dispatchEvent(new Event("resize"));
        viewport.dispatchEvent(new Event("scroll"));
      },
    });
  }, initial);
}

export async function setVisualViewport(page: Page, metrics: ViewportMetrics) {
  await page.evaluate((next) => {
    const testWindow = window as typeof window & {
      __setVisualViewportForTest?: (value: ViewportMetrics) => void;
    };
    testWindow.__setVisualViewportForTest?.(next);
  }, metrics);
}
