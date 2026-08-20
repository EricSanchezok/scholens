import { describe, expect, it } from "vitest";

import { isStandaloneDisplayMode } from "./display-mode";

function media(matches: boolean) {
  return { matches } as MediaQueryList;
}

describe("standalone display mode", () => {
  it("recognizes the standard display-mode media query", () => {
    expect(
      isStandaloneDisplayMode({
        matchMedia: () => media(true),
        navigatorObject: {} as Navigator,
      }),
    ).toBe(true);
  });

  it("recognizes the legacy iOS navigator flag", () => {
    expect(
      isStandaloneDisplayMode({
        matchMedia: () => media(false),
        navigatorObject: { standalone: true } as Navigator & {
          standalone: boolean;
        },
      }),
    ).toBe(true);
  });

  it("keeps an ordinary browser tab outside standalone mode", () => {
    expect(
      isStandaloneDisplayMode({
        matchMedia: () => media(false),
        navigatorObject: {} as Navigator,
      }),
    ).toBe(false);
  });
});
