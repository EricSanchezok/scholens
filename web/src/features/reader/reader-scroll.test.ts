import { describe, expect, it } from "vitest";

import { readerScrollTopForTarget } from "./reader-scroll";

describe("readerScrollTopForTarget", () => {
  it("aligns a target to the top of the container", () => {
    expect(
      readerScrollTopForTarget({
        container: {
          clientHeight: 800,
          scrollHeight: 3000,
          scrollTop: 500,
          top: 100,
        },
        target: { height: 100, top: 300 },
        alignment: "start",
      }),
    ).toBe(700);
  });

  it("centers a target inside the container", () => {
    expect(
      readerScrollTopForTarget({
        container: {
          clientHeight: 800,
          scrollHeight: 3000,
          scrollTop: 500,
          top: 100,
        },
        target: { height: 200, top: 500 },
        alignment: "center",
      }),
    ).toBe(600);
  });

  it("applies a start offset for sticky chrome clearance", () => {
    expect(
      readerScrollTopForTarget({
        alignment: "start",
        container: {
          clientHeight: 800,
          scrollHeight: 3000,
          scrollTop: 500,
          top: 100,
        },
        startOffset: 96,
        target: { height: 100, top: 300 },
      }),
    ).toBe(604);
  });

  it("clamps a target beyond the document end", () => {
    expect(
      readerScrollTopForTarget({
        container: {
          clientHeight: 800,
          scrollHeight: 1000,
          scrollTop: 0,
          top: 0,
        },
        target: { height: 100, top: 1200 },
        alignment: "start",
      }),
    ).toBe(200);
  });

  it("clamps a target above the document start", () => {
    expect(
      readerScrollTopForTarget({
        container: {
          clientHeight: 800,
          scrollHeight: 3000,
          scrollTop: 0,
          top: 0,
        },
        target: { height: 100, top: -100 },
        alignment: "start",
      }),
    ).toBe(0);
  });

  it("returns zero for a container without scrollable overflow", () => {
    expect(
      readerScrollTopForTarget({
        container: {
          clientHeight: 800,
          scrollHeight: 600,
          scrollTop: 0,
          top: 0,
        },
        target: { height: 100, top: 50 },
        alignment: "center",
      }),
    ).toBe(0);
  });
});
