import { describe, expect, it } from "vitest";

import { buildReaderReflowOutlineTree } from "./reader-reflow-outline";

describe("buildReaderReflowOutlineTree", () => {
  it("preserves heading hierarchy while keeping later peers at the root", () => {
    expect(
      buildReaderReflowOutlineTree([
        { id: "abstract", label: "Abstract", level: 2 },
        { id: "method", label: "2 Method", level: 2 },
        { id: "retrieval", label: "2.1 Retrieval", level: 3 },
        { id: "dense", label: "2.1.1 Dense retrieval", level: 4 },
        { id: "results", label: "3 Results", level: 2 },
      ]),
    ).toEqual([
      { children: [], id: "abstract", label: "Abstract", level: 2 },
      {
        children: [
          {
            children: [
              {
                children: [],
                id: "dense",
                label: "2.1.1 Dense retrieval",
                level: 4,
              },
            ],
            id: "retrieval",
            label: "2.1 Retrieval",
            level: 3,
          },
        ],
        id: "method",
        label: "2 Method",
        level: 2,
      },
      { children: [], id: "results", label: "3 Results", level: 2 },
    ]);
  });
});
