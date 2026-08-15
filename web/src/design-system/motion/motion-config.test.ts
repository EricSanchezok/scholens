import { describe, expect, it } from "vitest";

import { motionSprings } from "@/design-system/generated/motion-metadata";

import { motionTransitions } from "./motion-config";

describe("motion transition tokens", () => {
  it.each(["layout", "gentle"] as const)(
    "builds the %s spring from generated metadata",
    (name) => {
      expect(motionTransitions[name]).toEqual({
        type: "spring",
        ...motionSprings[name],
      });
    },
  );
});
