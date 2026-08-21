import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  parseColorSchemePreference,
  parseThemeName,
  storedColorSchemePreference,
  storedTheme,
} from "./theme-preference";
import { ThemeProvider, useTheme } from "./theme-provider";

function installColorSchemeMedia(initiallyDark: boolean) {
  let matches = initiallyDark;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_event: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) =>
      listeners.delete(listener),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  return (next: boolean) => {
    matches = next;
    listeners.forEach((listener) => listener());
  };
}

function Probe() {
  const {
    theme,
    colorScheme,
    colorSchemePreference,
    setTheme,
    setColorSchemePreference,
  } = useTheme();
  return (
    <div>
      <output>
        {theme}/{colorSchemePreference}/{colorScheme}
      </output>
      <button onClick={() => setTheme("default")} type="button">
        Use default theme
      </button>
      <button onClick={() => setColorSchemePreference("dark")} type="button">
        Use dark appearance
      </button>
    </div>
  );
}

describe("theme preference", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    localStorage.clear();
    document.cookie = "scholens-theme=; max-age=0; path=/";
    document.cookie = "scholens-color-scheme=; max-age=0; path=/";
    installColorSchemeMedia(false);
  });

  it("normalizes unsupported preferences", () => {
    expect(parseThemeName("default")).toBe("default");
    expect(parseThemeName("missing")).toBe("default");
    expect(parseColorSchemePreference("dark")).toBe("dark");
    expect(parseColorSchemePreference("sepia")).toBe("system");
  });

  it("prefers local storage over cookies", () => {
    document.cookie = "scholens-color-scheme=light; path=/";
    localStorage.setItem("scholens-color-scheme", "dark");

    expect(storedTheme()).toBe("default");
    expect(storedColorSchemePreference()).toBe("dark");
  });

  it("falls back to cookies when storage access is denied", () => {
    document.cookie = "scholens-color-scheme=dark; path=/";
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Storage access denied", "SecurityError");
    });

    expect(storedColorSchemePreference()).toBe("dark");
  });

  it("updates state and cookies when storage persistence is denied", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage access denied", "SecurityError");
    });
    render(
      <ThemeProvider
        initialColorSchemePreference="light"
        initialTheme="default"
      >
        <Probe />
      </ThemeProvider>,
    );

    act(() =>
      screen.getByRole("button", { name: "Use dark appearance" }).click(),
    );
    act(() =>
      screen.getByRole("button", { name: "Use default theme" }).click(),
    );

    expect(screen.getByRole("status")).toHaveTextContent("default/dark/dark");
    expect(document.cookie).toContain("scholens-color-scheme=dark");
    expect(document.cookie).toContain("scholens-theme=default");
  });

  it("follows system changes until an explicit appearance is selected", () => {
    const setDark = installColorSchemeMedia(false);
    render(
      <ThemeProvider
        initialColorSchemePreference="system"
        initialTheme="default"
      >
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "default/system/light",
    );
    act(() => setDark(true));
    expect(screen.getByRole("status")).toHaveTextContent("default/system/dark");
    expect(document.documentElement).toHaveAttribute(
      "data-color-scheme",
      "dark",
    );

    act(() =>
      screen.getByRole("button", { name: "Use dark appearance" }).click(),
    );
    expect(localStorage.getItem("scholens-color-scheme")).toBe("dark");
  });
});
