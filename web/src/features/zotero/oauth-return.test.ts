import { describe, expect, it } from "vitest";

import {
  buildZoteroReturnPath,
  clearZoteroCallbackParams,
  shouldOpenZoteroLibrary,
} from "./oauth-return";

describe("Zotero OAuth return state", () => {
  it("preserves product navigation while removing stale callback state", () => {
    expect(
      buildZoteroReturnPath(
        "/settings",
        "?section=connections&zotero=zotero_oauth_expired&zotero_intent=manage",
        "manage",
      ),
    ).toBe("/settings?section=connections");
  });

  it("marks Library returns so a successful callback reopens the chooser", () => {
    const returnPath = buildZoteroReturnPath(
      "/library",
      "?tab=papers&query=transformer",
      "import",
    );

    expect(returnPath).toBe(
      "/library?tab=papers&query=transformer&zotero_import=1",
    );
    expect(
      shouldOpenZoteroLibrary(
        "?tab=papers&zotero=connected&zotero_intent=import&zotero_import=1",
      ),
    ).toBe(true);
  });

  it("cleans callback keys without discarding unrelated Library state", () => {
    expect(
      clearZoteroCallbackParams(
        "?tab=papers&query=ai&zotero=zotero_rate_limited&zotero_intent=import&zotero_import=1",
      ).toString(),
    ).toBe("tab=papers&query=ai");
  });
});
