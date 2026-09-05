import { beforeEach, describe, expect, it } from "vitest";

import {
  readSessionState,
  removeSessionState,
  writeSessionState,
} from "./session-state";

describe("session state", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("round-trips JSON values and removes them", () => {
    expect(writeSessionState("test", { enabled: true })).toBe(true);
    expect(readSessionState("test")).toEqual({ enabled: true });

    removeSessionState("test");
    expect(readSessionState("test")).toBeUndefined();
  });

  it("treats malformed JSON as unavailable", () => {
    window.sessionStorage.setItem("test", "not-json");

    expect(readSessionState("test")).toBeUndefined();
  });
});
