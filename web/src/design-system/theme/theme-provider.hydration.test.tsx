import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/design-system/generated/theme-metadata", async (importOriginal) => {
  const metadata =
    await importOriginal<
      typeof import("@/design-system/generated/theme-metadata")
    >();
  return {
    ...metadata,
    themeNames: ["default", "fixture"],
  };
});

import { ThemeProvider, useTheme } from "./theme-provider";

function Probe() {
  const { theme } = useTheme();
  return <output>{theme}</output>;
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

it("hydrates deterministically before applying a persisted non-default theme", async () => {
  const serverMarkup = renderToString(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  const container = document.createElement("div");
  container.innerHTML = serverMarkup;
  document.body.append(container);
  expect(container).toHaveTextContent("default");
  localStorage.setItem("scholens-theme", "fixture");
  const onRecoverableError = vi.fn();

  let root: ReturnType<typeof hydrateRoot> | undefined;
  await act(async () => {
    root = hydrateRoot(
      container,
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
      { onRecoverableError },
    );
  });

  expect(onRecoverableError).not.toHaveBeenCalled();
  expect(container).toHaveTextContent("fixture");

  await act(async () => root?.unmount());
});
