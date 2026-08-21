import { expect, type Page, test } from "@playwright/test";

async function mockAnonymousSession(page: Page) {
  await page.route("**/api/v1/auth/bootstrap", async (route) => {
    await route.fulfill({
      body: JSON.stringify({
        code: "auth_session_missing",
        message: "session missing",
      }),
      contentType: "application/json",
      status: 401,
    });
  });
}

test("publishes complete product identity metadata and assets", async ({
  page,
  request,
}) => {
  await mockAnonymousSession(page);
  await page.goto("/login");

  await expect(page.locator('[data-product-mark="micro"]')).toBeVisible();
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    "href",
    "/manifest.webmanifest",
  );
  await expect(page.locator('link[rel="mask-icon"]')).toHaveAttribute(
    "href",
    "/brand/safari-pinned-tab.svg",
  );
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
    "content",
    "https://scholens.sanchezcloud.net/opengraph-image.png",
  );
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
    "content",
    "summary_large_image",
  );

  const manifestResponse = await request.get("/manifest.webmanifest");
  expect(manifestResponse.ok()).toBe(true);
  expect(manifestResponse.headers()["content-type"]).toContain(
    "application/manifest+json",
  );
  const manifest = (await manifestResponse.json()) as {
    display: string;
    icons: Array<{ purpose?: string; src: string }>;
    name: string;
  };
  expect(manifest).toMatchObject({ display: "standalone", name: "Scholens" });
  expect(manifest.icons.map(({ purpose }) => purpose)).toEqual(
    expect.arrayContaining(["maskable", "monochrome"]),
  );

  for (const icon of manifest.icons) {
    const response = await request.get(icon.src);
    expect(response.ok(), `${icon.src} should resolve`).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/");
  }
});

test("keeps the documentation lockup contained at the minimum width", async ({
  page,
}) => {
  await page.setViewportSize({ height: 568, width: 320 });
  await page.goto("/docs");

  await expect(
    page.locator('header [data-product-mark="micro"]'),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
