import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelPreparedZoteroAuthorization,
  clearPendingZoteroAuthorization,
  continueZoteroAuthorization,
  hasPendingZoteroAuthorization,
  prepareZoteroAuthorizationWindow,
} from "./oauth-navigation";

describe("installed Zotero OAuth navigation", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("prepares a browser window before awaiting the provider URL", () => {
    const prepared = { close: vi.fn(), location: { href: "about:blank" } };
    expect(
      prepareZoteroAuthorizationWindow({
        openWindow: () => prepared as unknown as Window,
        standalone: true,
      }),
    ).toBe(prepared);
  });

  it("keeps the installed app alive while OAuth continues externally", () => {
    const prepared = { close: vi.fn(), location: { href: "about:blank" } };
    const assign = vi.fn();
    expect(
      continueZoteroAuthorization(
        "https://www.zotero.org/oauth/authorize",
        prepared as unknown as Window,
        assign,
      ),
    ).toBe("external");
    expect(prepared.location.href).toBe(
      "https://www.zotero.org/oauth/authorize",
    );
    expect(assign).not.toHaveBeenCalled();
    expect(hasPendingZoteroAuthorization()).toBe(true);
    clearPendingZoteroAuthorization();
    expect(hasPendingZoteroAuthorization()).toBe(false);
  });

  it("retains same-tab OAuth in an ordinary browser", () => {
    const assign = vi.fn();
    continueZoteroAuthorization("https://www.zotero.org", undefined, assign);
    expect(assign).toHaveBeenCalledWith("https://www.zotero.org");
  });

  it("closes a prepared window when authorization setup fails", () => {
    const prepared = { close: vi.fn(), location: { href: "about:blank" } };
    cancelPreparedZoteroAuthorization(prepared as unknown as Window);
    expect(prepared.close).toHaveBeenCalledOnce();
  });
});
