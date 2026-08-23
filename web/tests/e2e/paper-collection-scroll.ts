import { expect, type Locator, type Page } from "@playwright/test";

export async function expectPaperCollectionScrollContained({
  page,
  toolbar,
}: {
  page: Page;
  toolbar: Locator;
}) {
  const scroller = page.locator("[data-paper-collection-scroll]");
  await expect(scroller).toBeVisible();
  await expect(toolbar).toBeVisible();

  const toolbarBefore = await toolbar.boundingBox();
  expect(toolbarBefore).not.toBeNull();
  await expect
    .poll(() =>
      scroller.evaluate((element) => {
        element.scrollTop = element.scrollHeight;
        return element.scrollHeight - element.scrollTop - element.clientHeight;
      }),
    )
    .toBeLessThanOrEqual(1);

  await scroller.hover();
  await page.mouse.wheel(0, 1_200);

  const result = await scroller.evaluate((element) => {
    const split = element.closest<HTMLElement>("[data-paper-collection-split]");
    const main = element.closest("main");
    const ancestorScrollOffsets: number[] = [];
    let ancestor = element.parentElement;
    while (ancestor && ancestor !== document.body) {
      ancestorScrollOffsets.push(ancestor.scrollTop);
      ancestor = ancestor.parentElement;
    }
    const splitBounds = split?.getBoundingClientRect();
    const mainBounds = main?.getBoundingClientRect();
    return {
      ancestorScrollOffsets,
      documentScrollTop: document.scrollingElement?.scrollTop ?? 0,
      hasOverflow: element.scrollHeight > element.clientHeight,
      mainBottom: mainBounds?.bottom,
      overscrollBehaviorY: getComputedStyle(element).overscrollBehaviorY,
      splitBottom: splitBounds?.bottom,
    };
  });
  const toolbarAfter = await toolbar.boundingBox();

  expect(result.hasOverflow).toBe(true);
  expect(result.overscrollBehaviorY).toBe("contain");
  expect(result.ancestorScrollOffsets.every((offset) => offset === 0)).toBe(
    true,
  );
  expect(result.documentScrollTop).toBe(0);
  expect(result.splitBottom).toBeLessThanOrEqual((result.mainBottom ?? 0) + 1);
  expect(Math.abs(toolbarAfter!.y - toolbarBefore!.y)).toBeLessThanOrEqual(1);
}
