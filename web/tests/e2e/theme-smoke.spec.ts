import { expect, test } from "@playwright/test";

test("resolves the system appearance before hydration", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-theme", "default");
    localStorage.setItem("scholens-color-scheme", "system");
  });

  await page.goto("/");

  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "default");
  await expect(root).toHaveAttribute("data-color-scheme", "dark");
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    )
    .toBe("rgb(20, 20, 18)");
});

test("falls back safely from stale theme and appearance values", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.addInitScript(() => {
    localStorage.setItem("scholens-theme", "retired-theme");
    localStorage.setItem("scholens-color-scheme", "sepia");
  });

  await page.goto("/");

  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "default");
  await expect(root).toHaveAttribute("data-color-scheme", "light");
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    )
    .toBe("rgb(250, 250, 248)");
});
