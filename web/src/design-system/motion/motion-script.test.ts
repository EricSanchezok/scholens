import { afterEach, expect, it, vi } from "vitest";

import { motionInitializationScript } from "./motion-script";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.motion;
  delete document.documentElement.dataset.motionPreference;
  document.cookie = "scholens-motion=; max-age=0; path=/";
});

it("falls back to the system preference when storage access is denied", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("Storage access denied", "SecurityError");
  });
  vi.stubGlobal("matchMedia", () => ({ matches: true }));

  Function(motionInitializationScript)();

  expect(document.documentElement).toHaveAttribute(
    "data-motion-preference",
    "system",
  );
  expect(document.documentElement).toHaveAttribute("data-motion", "reduced");
});
