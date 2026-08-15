import { describe, expect, it } from "vitest";

import { isImeComposing } from "./ime";

function keyboardEvent({
  isComposing = false,
  keyCode = 13,
}: {
  isComposing?: boolean;
  keyCode?: number;
}) {
  return { nativeEvent: { isComposing, keyCode } };
}

describe("IME keyboard guard", () => {
  it("recognizes the standards-based composition state", () => {
    expect(isImeComposing(keyboardEvent({ isComposing: true }))).toBe(true);
  });

  it("recognizes Safari's legacy IME process key", () => {
    expect(isImeComposing(keyboardEvent({ keyCode: 229 }))).toBe(true);
  });

  it("allows an ordinary Enter key after composition has finished", () => {
    expect(isImeComposing(keyboardEvent({}))).toBe(false);
  });
});
