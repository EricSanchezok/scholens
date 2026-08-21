import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { themeInitializationScript } from "./theme-script";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.colorScheme;
  document.documentElement.style.removeProperty("color-scheme");
});

beforeEach(() => {
  localStorage.clear();
  document.cookie = "scholens-theme=; max-age=0; path=/";
  document.cookie = "scholens-color-scheme=; max-age=0; path=/";
});

it("applies stored preferences before hydration", () => {
  localStorage.setItem("scholens-theme", "default");
  localStorage.setItem("scholens-color-scheme", "dark");
  vi.stubGlobal("matchMedia", () => ({ matches: false }));

  Function(themeInitializationScript)();

  expect(document.documentElement).toHaveAttribute("data-theme", "default");
  expect(document.documentElement).toHaveAttribute("data-color-scheme", "dark");
  expect(document.documentElement.style.colorScheme).toBe("dark");
});

it("falls back to cookies and the system scheme when storage is denied", () => {
  document.cookie = "scholens-theme=default; path=/";
  document.cookie = "scholens-color-scheme=system; path=/";
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("Storage access denied", "SecurityError");
  });
  vi.stubGlobal("matchMedia", () => ({ matches: true }));

  Function(themeInitializationScript)();

  expect(document.documentElement).toHaveAttribute("data-theme", "default");
  expect(document.documentElement).toHaveAttribute("data-color-scheme", "dark");
});

it("normalizes stale theme and appearance values", () => {
  localStorage.setItem("scholens-theme", "retired-theme");
  localStorage.setItem("scholens-color-scheme", "sepia");
  vi.stubGlobal("matchMedia", () => ({ matches: false }));

  Function(themeInitializationScript)();

  expect(document.documentElement).toHaveAttribute("data-theme", "default");
  expect(document.documentElement).toHaveAttribute(
    "data-color-scheme",
    "light",
  );
});
