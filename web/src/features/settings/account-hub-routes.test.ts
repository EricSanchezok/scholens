import { describe, expect, it } from "vitest";

import {
  accountHubBackHref,
  desktopSettingsHref,
  mobileSettingsHref,
  mobileSettingsRedirectHref,
  normalizeInternalReturnTo,
} from "./account-hub-routes";

describe("mobile account hub routes", () => {
  it("maps Settings sections to their mobile destinations", () => {
    expect(mobileSettingsHref("account")).toBe("/me/account");
    expect(mobileSettingsHref("usage")).toBe("/me/usage");
    expect(mobileSettingsHref("general")).toBe("/me/settings/display");
    expect(mobileSettingsHref("translation")).toBe("/me/settings/translation");
    expect(mobileSettingsHref("connections")).toBe("/me/connections");
    expect(mobileSettingsHref("access-keys")).toBe("/me/access-keys");
  });

  it("keeps only internal return targets", () => {
    expect(normalizeInternalReturnTo("/library?tab=papers#recent")).toBe(
      "/library?tab=papers#recent",
    );
    expect(normalizeInternalReturnTo("https://example.com/library")).toBe(
      undefined,
    );
    expect(normalizeInternalReturnTo("//example.com/library")).toBe(undefined);
    expect(normalizeInternalReturnTo("javascript:alert(1)")).toBe(undefined);
    expect(normalizeInternalReturnTo("library")).toBe(undefined);
  });

  it("prefers a validated source and otherwise uses the fixed parent", () => {
    expect(accountHubBackHref("connections", "/library?tab=papers")).toBe(
      "/library?tab=papers",
    );
    expect(accountHubBackHref("display")).toBe("/me/settings");
    expect(accountHubBackHref("settings")).toBe("/me");
    expect(accountHubBackHref("usage", "https://example.com")).toBe("/me");
  });

  it("preserves Zotero callback state without leaking unrelated parameters", () => {
    const callback = new URLSearchParams(
      "zotero=connected&zotero_intent=manage&zotero_import=complete&ignored=value",
    );
    expect(
      mobileSettingsHref("connections", {
        callbackParams: callback,
        returnTo: "/library?tab=papers",
      }),
    ).toBe(
      "/me/connections?returnTo=%2Flibrary%3Ftab%3Dpapers&zotero=connected&zotero_intent=manage&zotero_import=complete",
    );
  });

  it("replaces a legacy Settings query while retaining workspace state", () => {
    const params = new URLSearchParams(
      "conversation=abc&settings=connections&zotero=connected&zotero_intent=manage",
    );
    expect(mobileSettingsRedirectHref("connections", "/", params)).toBe(
      "/me/connections?returnTo=%2F%3Fconversation%3Dabc&zotero=connected&zotero_intent=manage",
    );
  });

  it("maps direct desktop account-hub paths back to the existing dialog", () => {
    expect(desktopSettingsHref("home")).toBe("/?settings=account");
    expect(desktopSettingsHref("settings")).toBe("/?settings=general");
    expect(desktopSettingsHref("display")).toBe("/?settings=general");
    expect(desktopSettingsHref("translation")).toBe("/?settings=translation");
    expect(desktopSettingsHref("accessKeys")).toBe("/?settings=access-keys");
  });
});
