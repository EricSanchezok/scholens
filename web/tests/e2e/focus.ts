import { expect, type Locator } from "@playwright/test";

let sentinelSequence = 0;

/** Focuses the target through the browser's natural Tab order. */
export async function focusThroughTab(target: Locator) {
  const page = target.page();
  const sentinelId = `focus-sentinel-${sentinelSequence++}`;
  await target.evaluate((element, id) => {
    const sentinel = document.createElement("button");
    sentinel.dataset.focusTestSentinel = id;
    sentinel.style.cssText =
      "position:fixed;width:1px;height:1px;opacity:0;pointer-events:none";
    element.before(sentinel);
    sentinel.focus();
  }, sentinelId);
  await page.keyboard.press("Tab");
  await expect(target).toBeFocused();
  await page
    .locator(`[data-focus-test-sentinel="${sentinelId}"]`)
    .evaluate((element) => element.remove());
}
