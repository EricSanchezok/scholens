import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MotionProvider,
  parseMotionPreference,
  storedMotionPreference,
  useMotionPreference,
} from "./motion-provider";

function installMotionMedia(reduced: boolean) {
  let matches = reduced;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return matches;
    },
    media: "(prefers-reduced-motion: reduce)",
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
  const { preference, resolved, setPreference } = useMotionPreference();
  return (
    <button onClick={() => setPreference("full")} type="button">
      {preference}:{resolved}
    </button>
  );
}

describe("motion preference", () => {
  afterEach(() => vi.restoreAllMocks());

  beforeEach(() => {
    localStorage.clear();
    document.cookie = "scholens-motion=; max-age=0; path=/";
    installMotionMedia(false);
  });

  it("normalizes unsupported stored values", () => {
    expect(parseMotionPreference("reduced")).toBe("reduced");
    expect(parseMotionPreference("loud")).toBe("system");
    expect(parseMotionPreference(null)).toBe("system");
  });

  it("prefers local storage over the cookie", () => {
    document.cookie = "scholens-motion=reduced; path=/";
    localStorage.setItem("scholens-motion", "full");
    expect(storedMotionPreference()).toBe("full");
  });

  it("falls back to the cookie when storage access is denied", () => {
    document.cookie = "scholens-motion=reduced; path=/";
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Storage access denied", "SecurityError");
    });

    expect(storedMotionPreference()).toBe("reduced");
  });

  it("updates state and the cookie when storage persistence is denied", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage access denied", "SecurityError");
    });
    render(
      <MotionProvider initialPreference="reduced">
        <Probe />
      </MotionProvider>,
    );

    act(() => screen.getByRole("button").click());

    expect(screen.getByRole("button")).toHaveTextContent("full:full");
    expect(document.cookie).toContain("scholens-motion=full");
  });

  it("resolves system changes and persists an explicit override", () => {
    const setReduced = installMotionMedia(false);
    render(
      <MotionProvider initialPreference="system">
        <Probe />
      </MotionProvider>,
    );

    expect(screen.getByRole("button")).toHaveTextContent("system:full");
    act(() => setReduced(true));
    expect(screen.getByRole("button")).toHaveTextContent("system:reduced");
    expect(document.documentElement).toHaveAttribute("data-motion", "reduced");

    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button")).toHaveTextContent("full:full");
    expect(localStorage.getItem("scholens-motion")).toBe("full");
    expect(document.cookie).toContain("scholens-motion=full");
  });
});
